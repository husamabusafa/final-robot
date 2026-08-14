"""Benchmark the lightweight vision stack on the Reachy Mini's Pi.

Tests:
  1. YuNet face detector (cv2.FaceDetectorYN) at multiple input sizes
  2. SFace feature extractor (cv2.FaceRecognizerSF) — per-face cost
  3. Mouth-motion energy (ROI variance on SFace's aligned 112x112 crop)
  4. Full pipeline: detect -> align -> recognize -> mouth energy

No torch, no ultralytics. Just OpenCV + two ONNX files (~37 MB total).

Run on the Pi:
    source /venvs/apps_venv/bin/activate
    pip install opencv-contrib-python   # if not already installed
    python /home/pollen/bench_yunet.py
"""
from __future__ import annotations

import sys
import time
import urllib.request
from pathlib import Path
from collections import deque

import cv2
import numpy as np

# --- Model URLs (OpenCV Zoo) ------------------------------------------------

MODEL_DIR = Path(__file__).resolve().parent / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

YUNET_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
YUNET_PATH = MODEL_DIR / "face_detection_yunet_2023mar.onnx"

SFACE_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx"
SFACE_PATH = MODEL_DIR / "face_recognition_sface_2021dec.onnx"

# --- Config -----------------------------------------------------------------

INPUT_SIZES = [160, 256, 320, 480, 640]  # px (long edge)
WARMUP = 5
TIMED = 30
CONF_THRESHOLD = 0.5
NMS_THRESHOLD = 0.3
TOP_K = 5000

MOUTH_BUF_LEN = 15  # ~0.5s at 30fps


# --- Helpers ----------------------------------------------------------------

def download(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  cached: {dest.name} ({dest.stat().st_size / 1e6:.1f} MB)")
        return
    print(f"  downloading {dest.name} from {url} ...")
    urllib.request.urlretrieve(url, str(dest))
    print(f"  saved: {dest.name} ({dest.stat().st_size / 1e6:.1f} MB)")


def get_frame():
    """Grab one frame from the robot camera, fallback to synthetic."""
    try:
        from reachy_mini import ReachyMini
        mini = ReachyMini(media_backend="default")
        for _ in range(10):
            f = mini.media.get_frame()
            if f is not None:
                if f.ndim == 3 and f.shape[2] == 3:
                    f = cv2.cvtColor(f, cv2.COLOR_RGB2BGR)
                print(f"[camera] robot camera: {f.shape[1]}x{f.shape[0]}")
                return f, mini
            time.sleep(0.1)
        print("[camera] robot camera returned None, using synthetic frame")
        mini.__exit__(None, None, None)
    except Exception as exc:
        print(f"[camera] robot camera unavailable: {exc}")

    print("[camera] using synthetic 640x480 frame")
    return (np.random.rand(480, 640, 3) * 255).astype(np.uint8), None


def detect_faces(detector: cv2.FaceDetectorYN, frame: np.ndarray):
    """Run YuNet and return just the faces array, handling both OpenCV 4.x
    (returns ndarray) and 5.x (returns (retval, ndarray))."""
    result = detector.detect(frame)
    if isinstance(result, tuple):
        # OpenCV 5.x: (retval, faces)
        return result[1]
    return result


def resize_for_inference(frame: np.ndarray, target_long_edge: int) -> np.ndarray:
    h, w = frame.shape[:2]
    scale = target_long_edge / max(h, w)
    if scale >= 1.0:
        return frame
    return cv2.resize(frame, (int(w * scale), int(h * scale)))


# --- Benchmarks -------------------------------------------------------------

def bench_yunet(detector: cv2.FaceDetectorYN, frame: np.ndarray, size: int) -> dict:
    """Benchmark YuNet detection at a given input size."""
    resized = resize_for_inference(frame, size)
    rh, rw = resized.shape[:2]
    detector.setInputSize((rw, rh))

    # Warmup
    for _ in range(WARMUP):
        detect_faces(detector, resized)

    latencies = []
    n_faces = 0
    for _ in range(TIMED):
        t0 = time.perf_counter()
        faces = detect_faces(detector, resized)
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)
        n_faces = faces.shape[0] if faces is not None else 0

    arr = np.array(latencies)
    return {
        "size": size,
        "mean_ms": float(arr.mean()),
        "std_ms": float(arr.std()),
        "p95_ms": float(np.percentile(arr, 95)),
        "fps": 1000.0 / float(arr.mean()),
        "n_faces": n_faces,
    }


def bench_sface(recognizer: cv2.FaceRecognizerSF, frame: np.ndarray,
                detector: cv2.FaceDetectorYN, size: int) -> dict:
    """Benchmark SFace align + feature extraction for each detected face."""
    resized = resize_for_inference(frame, size)
    rh, rw = resized.shape[:2]
    detector.setInputSize((rw, rh))
    faces = detect_faces(detector, resized)

    if faces is None or faces.shape[0] == 0:
        # No faces — create a dummy face row so we can still time SFace
        # YuNet returns rows of [x, y, w, h, re_x, re_y, le_x, le_y, ...]
        faces = np.array([[rw // 4, rh // 4, rw // 2, rh // 2,
                           rw // 3, rh // 3, 2 * rw // 3, rh // 3,
                           rw // 2, 2 * rh // 3, rw // 3, 2 * rh // 3,
                           2 * rw // 3, 2 * rh // 3, 0.9]], dtype=np.float32)

    n = faces.shape[0]

    # Warmup
    for _ in range(WARMUP):
        for i in range(n):
            recognizer.alignCrop(resized, faces[i])
            f = recognizer.feature(recognizer.alignCrop(resized, faces[i]))

    latencies_align = []
    latencies_feat = []
    for _ in range(TIMED):
        for i in range(n):
            t0 = time.perf_counter()
            aligned = recognizer.alignCrop(resized, faces[i])
            t1 = time.perf_counter()
            feat = recognizer.feature(aligned)
            t2 = time.perf_counter()
            latencies_align.append((t1 - t0) * 1000.0)
            latencies_feat.append((t2 - t1) * 1000.0)

    a = np.array(latencies_align)
    f = np.array(latencies_feat)
    return {
        "size": size,
        "n_faces": n,
        "align_mean_ms": float(a.mean()),
        "feat_mean_ms": float(f.mean()),
        "per_face_ms": float((a + f).mean()),
        "total_ms": float((a + f).sum() / TIMED),  # all faces per frame
    }


def bench_mouth_energy(recognizer: cv2.FaceRecognizerSF, frame: np.ndarray,
                       detector: cv2.FaceDetectorYN, size: int) -> dict:
    """Benchmark the mouth-motion energy trick on SFace's aligned crop."""
    resized = resize_for_inference(frame, size)
    rh, rw = resized.shape[:2]
    detector.setInputSize((rw, rh))
    faces = detect_faces(detector, resized)

    if faces is None or faces.shape[0] == 0:
        faces = np.array([[rw // 4, rh // 4, rw // 2, rh // 2,
                           rw // 3, rh // 3, 2 * rw // 3, rh // 3,
                           rw // 2, 2 * rh // 3, rw // 3, 2 * rh // 3,
                           2 * rw // 3, 2 * rh // 3, 0.9]], dtype=np.float32)

    n = faces.shape[0]
    bufs = [deque(maxlen=MOUTH_BUF_LEN) for _ in range(n)]

    # Warmup: fill buffers
    for _ in range(MOUTH_BUF_LEN + WARMUP):
        for i in range(n):
            aligned = recognizer.alignCrop(resized, faces[i])
            mouth = cv2.cvtColor(aligned[74:112, 28:84], cv2.COLOR_BGR2GRAY)
            mouth = cv2.GaussianBlur(mouth, (5, 5), 0).astype(np.float32) / 255.0
            bufs[i].append(mouth)

    latencies = []
    for _ in range(TIMED):
        t0 = time.perf_counter()
        for i in range(n):
            aligned = recognizer.alignCrop(resized, faces[i])
            mouth = cv2.cvtColor(aligned[74:112, 28:84], cv2.COLOR_BGR2GRAY)
            mouth = cv2.GaussianBlur(mouth, (5, 5), 0).astype(np.float32) / 255.0
            bufs[i].append(mouth)
            if len(bufs[i]) > 5:
                _ = float(np.mean(np.var(np.stack(bufs[i]), axis=0)))
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)

    arr = np.array(latencies)
    return {
        "size": size,
        "n_faces": n,
        "mean_ms": float(arr.mean()),
        "per_face_ms": float(arr.mean() / max(n, 1)),
        "fps": 1000.0 / float(arr.mean()),
    }


def bench_full_pipeline(detector: cv2.FaceDetectorYN,
                        recognizer: cv2.FaceRecognizerSF,
                        frame: np.ndarray, size: int) -> dict:
    """Full per-frame pipeline: detect -> align -> feature -> mouth energy."""
    resized = resize_for_inference(frame, size)
    rh, rw = resized.shape[:2]
    detector.setInputSize((rw, rh))

    bufs = {}

    # Warmup
    for _ in range(WARMUP):
        faces = detect_faces(detector, resized)
        if faces is not None:
            for i in range(faces.shape[0]):
                aligned = recognizer.alignCrop(resized, faces[i])
                _ = recognizer.feature(aligned)
                mouth = cv2.cvtColor(aligned[74:112, 28:84], cv2.COLOR_BGR2GRAY)
                mouth = cv2.GaussianBlur(mouth, (5, 5), 0).astype(np.float32) / 255.0
                bufs.setdefault(i, deque(maxlen=MOUTH_BUF_LEN))
                bufs[i].append(mouth)
                if len(bufs[i]) > 5:
                    _ = float(np.mean(np.var(np.stack(bufs[i]), axis=0)))

    latencies = []
    n_faces = 0
    for _ in range(TIMED):
        t0 = time.perf_counter()
        faces = detect_faces(detector, resized)
        n_faces = faces.shape[0] if faces is not None else 0
        if faces is not None:
            for i in range(faces.shape[0]):
                aligned = recognizer.alignCrop(resized, faces[i])
                feat = recognizer.feature(aligned)
                mouth = cv2.cvtColor(aligned[74:112, 28:84], cv2.COLOR_BGR2GRAY)
                mouth = cv2.GaussianBlur(mouth, (5, 5), 0).astype(np.float32) / 255.0
                bufs.setdefault(i, deque(maxlen=MOUTH_BUF_LEN))
                bufs[i].append(mouth)
                if len(bufs[i]) > 5:
                    _ = float(np.mean(np.var(np.stack(bufs[i]), axis=0)))
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)

    arr = np.array(latencies)
    return {
        "size": size,
        "n_faces": n_faces,
        "mean_ms": float(arr.mean()),
        "p95_ms": float(np.percentile(arr, 95)),
        "fps": 1000.0 / float(arr.mean()),
    }


# --- Main -------------------------------------------------------------------

def main() -> int:
    print("=" * 70)
    print("Lightweight Vision Benchmark: YuNet + SFace + Mouth Energy")
    print("Reachy Mini (Raspberry Pi CM4)")
    print("=" * 70)
    print(f"OpenCV: {cv2.__version__}")
    print()

    # Check that we have the face detection modules
    if not hasattr(cv2, "FaceDetectorYN"):
        print("ERROR: cv2.FaceDetectorYN not found.", file=sys.stderr)
        print("Install opencv-contrib-python:", file=sys.stderr)
        print("  pip install opencv-contrib-python --force-reinstall", file=sys.stderr)
        return 1
    if not hasattr(cv2, "FaceRecognizerSF"):
        print("ERROR: cv2.FaceRecognizerSF not found.", file=sys.stderr)
        print("Install opencv-contrib-python:", file=sys.stderr)
        print("  pip install opencv-contrib-python --force-reinstall", file=sys.stderr)
        return 1

    # Download models
    print("Downloading models...")
    download(YUNET_URL, YUNET_PATH)
    download(SFACE_URL, SFACE_PATH)
    print()

    # Load models
    print("Loading models...")
    detector = cv2.FaceDetectorYN.create(
        str(YUNET_PATH), "", (320, 320),
        score_threshold=CONF_THRESHOLD,
        nms_threshold=NMS_THRESHOLD,
        top_k=TOP_K,
    )
    recognizer = cv2.FaceRecognizerSF.create(str(SFACE_PATH), "")
    print("  YuNet loaded")
    print("  SFace loaded")
    print()

    # Get a frame
    print("Getting camera frame...")
    frame, mini_handle = get_frame()
    if frame is None:
        print("No frame available.", file=sys.stderr)
        return 1
    h, w = frame.shape[:2]
    print(f"  frame: {w}x{h}")
    print()

    # --- 1. YuNet detection -------------------------------------------------
    print("=" * 70)
    print("1. YuNet Face Detection")
    print("=" * 70)
    print(f"{'size':>6} | {'mean (ms)':>10} | {'std':>6} | {'p95':>7} | {'FPS':>7} | {'faces':>5}")
    print("-" * 60)
    yunet_results = []
    for sz in INPUT_SIZES:
        try:
            r = bench_yunet(detector, frame, sz)
            yunet_results.append(r)
            print(f"{r['size']:>6} | {r['mean_ms']:>10.1f} | {r['std_ms']:>6.1f} | "
                  f"{r['p95_ms']:>7.1f} | {r['fps']:>7.1f} | {r['n_faces']:>5}")
        except Exception as exc:
            print(f"{sz:>6} | ERROR: {exc}")
    print()

    # --- 2. SFace align + feature -------------------------------------------
    print("=" * 70)
    print("2. SFace Align + Feature Extraction")
    print("=" * 70)
    print(f"{'size':>6} | {'faces':>5} | {'align (ms)':>10} | {'feat (ms)':>9} | "
          f"{'per-face':>8} | {'total (ms)':>9}")
    print("-" * 70)
    sface_results = []
    for sz in INPUT_SIZES:
        try:
            r = bench_sface(recognizer, frame, detector, sz)
            sface_results.append(r)
            print(f"{r['size']:>6} | {r['n_faces']:>5} | {r['align_mean_ms']:>10.1f} | "
                  f"{r['feat_mean_ms']:>9.1f} | {r['per_face_ms']:>8.1f} | {r['total_ms']:>9.1f}")
        except Exception as exc:
            print(f"{sz:>6} | ERROR: {exc}")
    print()

    # --- 3. Mouth energy ----------------------------------------------------
    print("=" * 70)
    print("3. Mouth-Motion Energy (ROI variance on SFace aligned crop)")
    print("=" * 70)
    print(f"{'size':>6} | {'faces':>5} | {'mean (ms)':>10} | {'per-face':>8} | {'FPS':>7}")
    print("-" * 55)
    mouth_results = []
    for sz in INPUT_SIZES:
        try:
            r = bench_mouth_energy(recognizer, frame, detector, sz)
            mouth_results.append(r)
            print(f"{r['size']:>6} | {r['n_faces']:>5} | {r['mean_ms']:>10.1f} | "
                  f"{r['per_face_ms']:>8.1f} | {r['fps']:>7.1f}")
        except Exception as exc:
            print(f"{sz:>6} | ERROR: {exc}")
    print()

    # --- 4. Full pipeline ---------------------------------------------------
    print("=" * 70)
    print("4. Full Pipeline: detect + align + feature + mouth energy")
    print("=" * 70)
    print(f"{'size':>6} | {'faces':>5} | {'mean (ms)':>10} | {'p95':>7} | {'FPS':>7}")
    print("-" * 55)
    full_results = []
    for sz in INPUT_SIZES:
        try:
            r = bench_full_pipeline(detector, recognizer, frame, sz)
            full_results.append(r)
            print(f"{r['size']:>6} | {r['n_faces']:>5} | {r['mean_ms']:>10.1f} | "
                  f"{r['p95_ms']:>7.1f} | {r['fps']:>7.1f}")
        except Exception as exc:
            print(f"{sz:>6} | ERROR: {exc}")
    print()

    # --- Summary ------------------------------------------------------------
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    if yunet_results:
        best = max(yunet_results, key=lambda r: r["fps"])
        print(f"YuNet best:  {best['size']}px -> {best['mean_ms']:.1f} ms ({best['fps']:.1f} FPS)")
    if full_results:
        best = max(full_results, key=lambda r: r["fps"])
        print(f"Full pipeline best: {best['size']}px -> {best['mean_ms']:.1f} ms ({best['fps']:.1f} FPS)")
        target = 15.0
        capable = [r for r in full_results if r["fps"] >= target]
        if capable:
            print(f"Sizes hitting >= {target} FPS: {', '.join(str(r['size']) for r in capable)} px")
        else:
            best = max(full_results, key=lambda r: r["fps"])
            print(f"Best achievable: {best['fps']:.1f} FPS at {best['size']}px "
                  f"(target: {target} FPS)")
    print()

    # Cleanup
    if mini_handle is not None:
        mini_handle.__exit__(None, None, None)

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
