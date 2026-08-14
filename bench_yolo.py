"""Benchmark YOLOv8-Pose inference speed on the Reachy Mini's Raspberry Pi.

Tests the same model your tracker uses (yolov8n-pose) at several image sizes
and reports per-frame latency + effective FPS. Uses the robot's camera
(mini.media.get_frame()) so the numbers reflect the real pipeline.

Run on the Pi:
    source /venvs/apps_venv/bin/activate
    pip install ultralytics   # if not already installed
    python /home/pollen/bench_yolo.py

Keys (if preview is shown): q / ESC to quit early.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2
import numpy as np

try:
    from ultralytics import YOLO
except ImportError:
    print("ultralytics is not installed. Run:", file=sys.stderr)
    print("  pip install ultralytics", file=sys.stderr)
    sys.exit(1)

try:
    import torch
    _TORCH_OK = True
except ImportError:
    _TORCH_OK = False


# --- Config -----------------------------------------------------------------

MODEL_NAME = "yolov8n-pose.pt"          # nano — smallest, fastest
MODEL_DIR = Path(__file__).resolve().parent / "models"
IMAGE_SIZES = [160, 256, 320, 480, 640]  # px — inference input size
WARMUP_ITERS = 3                          # warmup runs (not timed)
TIMED_ITERS = 20                          # timed runs per size
CONF = 0.35

# Camera source: "robot" = mini.media.get_frame(), "usb" = cv2.VideoCapture(0)
CAMERA_SOURCE = "robot"
FALLBACK_SYNTHETIC = True  # if no camera, use a synthetic frame


def get_frame_factory():
    """Return a callable () -> np.ndarray (BGR) or None if no camera."""
    if CAMERA_SOURCE == "robot":
        try:
            from reachy_mini import ReachyMini
            mini = ReachyMini(media_backend="default")
            print("[camera] Using robot camera via mini.media.get_frame()")
            def grab():
                f = mini.media.get_frame()
                if f is None:
                    return None
                # Frame may be RGB; convert to BGR for OpenCV/ultralytics
                if f.ndim == 3 and f.shape[2] == 3:
                    f = cv2.cvtColor(f, cv2.COLOR_RGB2BGR)
                return f
            return grab, mini
        except Exception as exc:
            print(f"[camera] Robot camera unavailable: {exc}", file=sys.stderr)
            if not FALLBACK_SYNTHETIC:
                return None, None
    elif CAMERA_SOURCE == "usb":
        cap = cv2.VideoCapture(0)
        if cap.isOpened():
            print("[camera] Using USB camera (cv2.VideoCapture(0))")
            def grab():
                ok, f = cap.read()
                return f if ok else None
            return grab, cap
        cap.release()
        print("[camera] USB camera unavailable", file=sys.stderr)
        if not FALLBACK_SYNTHETIC:
            return None, None

    # Synthetic fallback — a random 640x480 image (worst case, no structure)
    print("[camera] Using synthetic 640x480 frame")
    synth = (np.random.rand(480, 640, 3) * 255).astype(np.uint8)
    return (lambda: synth.copy()), None


def benchmark_size(model: YOLO, frame: np.ndarray, imgsz: int) -> dict:
    """Run WARMUP + TIMED iterations at a given image size."""
    # Warmup
    for _ in range(WARMUP_ITERS):
        model(frame, imgsz=imgsz, conf=CONF, verbose=False)

    latencies = []
    n_people = 0
    for _ in range(TIMED_ITERS):
        t0 = time.perf_counter()
        results = model(frame, imgsz=imgsz, conf=CONF, verbose=False)
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)  # ms
        n_people = len(results[0].boxes) if results and results[0].boxes is not None else 0

    arr = np.array(latencies)
    return {
        "imgsz": imgsz,
        "mean_ms": float(arr.mean()),
        "std_ms": float(arr.std()),
        "min_ms": float(arr.min()),
        "max_ms": float(arr.max()),
        "p95_ms": float(np.percentile(arr, 95)),
        "fps": 1000.0 / float(arr.mean()),
        "n_people": n_people,
    }


def main() -> int:
    print("=" * 64)
    print("YOLOv8-Pose Benchmark on Reachy Mini (Raspberry Pi CM4)")
    print("=" * 64)

    if _TORCH_OK:
        print(f"torch: {torch.__version__}")
        print(f"  CUDA available: {torch.cuda.is_available()}")
        print(f"  MPS available:   {torch.backends.mps.is_available()}")
        print(f"  threads:         {torch.get_num_threads()}")
    else:
        print("torch: not imported")

    import ultralytics
    print(f"ultralytics: {ultralytics.__version__}")
    print()

    # --- Load model ----------------------------------------------------------
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model_path = MODEL_DIR / MODEL_NAME
    if not model_path.exists():
        print(f"Downloading {MODEL_NAME} to {model_path} ...")
    else:
        print(f"Using cached model: {model_path}")

    try:
        model = YOLO(str(model_path))
    except Exception as exc:
        # Let ultralytics download it from the default hub
        print(f"Direct load failed ({exc}), trying hub download...")
        model = YOLO(MODEL_NAME)
        # Move the downloaded weights into our cache dir
        default_path = Path(MODEL_NAME)
        if default_path.exists() and not model_path.exists():
            default_path.rename(model_path)

    print(f"Model loaded: {model.model_name if hasattr(model, 'model_name') else MODEL_NAME}")
    print()

    # --- Get a frame ---------------------------------------------------------
    grabber, handle = get_frame_factory()
    if grabber is None:
        print("No camera available and synthetic fallback disabled.", file=sys.stderr)
        return 1

    frame = grabber()
    if frame is None:
        print("Could not grab a frame.", file=sys.stderr)
        return 1
    h, w = frame.shape[:2]
    print(f"Frame: {w}x{h} dtype={frame.dtype}")
    print()

    # --- Run benchmarks ------------------------------------------------------
    print(f"{'imgsz':>6} | {'mean (ms)':>10} | {'std':>6} | {'min':>7} | {'max':>7} | "
          f"{'p95':>7} | {'FPS':>7} | {'people':>6}")
    print("-" * 80)

    results = []
    for imgsz in IMAGE_SIZES:
        try:
            r = benchmark_size(model, frame, imgsz)
            results.append(r)
            print(f"{r['imgsz']:>6} | {r['mean_ms']:>10.1f} | {r['std_ms']:>6.1f} | "
                  f"{r['min_ms']:>7.1f} | {r['max_ms']:>7.1f} | {r['p95_ms']:>7.1f} | "
                  f"{r['fps']:>7.1f} | {r['n_people']:>6}")
        except Exception as exc:
            print(f"{imgsz:>6} | ERROR: {exc}")

    print()
    print("=" * 64)
    print("Summary")
    print("=" * 64)
    if results:
        fastest = min(results, key=lambda r: r["mean_ms"])
        slowest = max(results, key=lambda r: r["mean_ms"])
        print(f"Fastest: {fastest['imgsz']}px -> {fastest['mean_ms']:.1f} ms "
              f"({fastest['fps']:.1f} FPS)")
        print(f"Slowest: {slowest['imgsz']}px -> {slowest['mean_ms']:.1f} ms "
              f"({slowest['fps']:.1f} FPS)")
        print()
        # Verdict for real-time tracking
        target_fps = 15.0
        realtime_capable = [r for r in results if r["fps"] >= target_fps]
        if realtime_capable:
            print(f"Sizes that hit >= {target_fps} FPS: "
                  f"{', '.join(str(r['imgsz']) for r in realtime_capable)} px")
        else:
            print(f"NO size hit {target_fps} FPS — YOLOv8-Pose is NOT real-time on this Pi.")
            best = max(results, key=lambda r: r["fps"])
            print(f"Best achievable: {best['fps']:.1f} FPS at {best['imgsz']}px")
    print()

    # --- Cleanup -------------------------------------------------------------
    if handle is not None:
        if hasattr(handle, "release"):
            handle.release()
        elif hasattr(handle, "__exit__"):
            handle.__exit__(None, None, None)
        elif hasattr(handle, "close"):
            handle.close()

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
