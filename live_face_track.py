"""Live face-tracking demo for the wireless Reachy Mini.

Uses the SDK's built-in daemon-side head tracking (start_head_tracking)
for smooth, optimized face following. YuNet runs only for browser
visualization (boxes, landmarks). SFace runs occasionally for face ID.

Run on the Pi:
    source /venvs/apps_venv/bin/activate
    python /home/pollen/live_face_track.py

Then open in your Mac's browser:
    http://reachy-mini.local:8080/

Press Ctrl-C in the SSH session to quit.
"""
from __future__ import annotations

import sys
import threading
import time
import urllib.request
from collections import deque
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

import cv2
import numpy as np
from reachy_mini import ReachyMini

# --- Config -----------------------------------------------------------------

MODEL_DIR = Path(__file__).resolve().parent / "models"
YUNET_PATH = MODEL_DIR / "face_detection_yunet_2023mar.onnx"
SFACE_PATH = MODEL_DIR / "face_recognition_sface_2021dec.onnx"

YUNET_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
SFACE_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx"

INFER_SIZE = 320
CONF_THRESHOLD = 0.5
NMS_THRESHOLD = 0.3
TOP_K = 5000

HTTP_PORT = 8080

# SFace runs every N frames for ID (not every frame — 120ms is too slow)
SFACE_INTERVAL = 30  # ~1x/sec at 30 FPS, ~6x/sec at 5 FPS

# Mouth energy config
MOUTH_BUF_LEN = 15
MOUTH_ENERGY_FLOOR = 0.002


# --- Model download ---------------------------------------------------------

def download(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  downloading {dest.name}...")
    urllib.request.urlretrieve(url, str(dest))


def detect_faces(detector: cv2.FaceDetectorYN, frame: np.ndarray):
    """YuNet detect, handling OpenCV 4.x and 5.x return formats."""
    result = detector.detect(frame)
    if isinstance(result, tuple):
        return result[1]
    return result


# --- Shared state -----------------------------------------------------------

class AppState:
    def __init__(self):
        self.lock = threading.Lock()
        self.latest_jpeg: bytes = b""
        self.running = True
        self.fps = 0.0
        self.n_faces = 0
        self.speaker_id = -1
        self.tracking_active = False

    def set_frame(self, jpeg: bytes, fps: float, n_faces: int,
                  speaker_id: int, tracking: bool):
        with self.lock:
            self.latest_jpeg = jpeg
            self.fps = fps
            self.n_faces = n_faces
            self.speaker_id = speaker_id
            self.tracking_active = tracking

    def get_frame(self) -> bytes:
        with self.lock:
            return self.latest_jpeg


state = AppState()


# --- HTTP MJPEG server ------------------------------------------------------

class MJPEGHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            html = (
                "<!DOCTYPE html><html><head><title>Reachy Mini Live</title>"
                "<style>body{margin:0;background:#111;display:flex;"
                "flex-direction:column;align-items:center;justify-content:center;"
                "height:100vh;font-family:monospace;color:#0f0}"
                "img{max-width:90vw;max-height:80vh;border:2px solid #0f0}"
                "h2{margin:10px}</style></head>"
                "<body><h2>Reachy Mini - Live Face Tracking</h2>"
                f"<img src='/stream' alt='stream'></body></html>"
            )
            self.wfile.write(html.encode())
        elif self.path == "/stream":
            self.send_response(200)
            self.send_header("Age", "0")
            self.send_header("Cache-Control", "no-cache, private")
            self.send_header("Pragma", "no-cache")
            self.send_header(
                "Content-Type",
                "multipart/x-mixed-replace; boundary=FRAME",
            )
            self.end_headers()
            try:
                while state.running:
                    jpeg = state.get_frame()
                    if not jpeg:
                        time.sleep(0.05)
                        continue
                    self.wfile.write(b"--FRAME\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode())
                    self.wfile.write(jpeg)
                    self.wfile.write(b"\r\n")
                    time.sleep(0.033)  # ~30 FPS cap
            except (BrokenPipeError, ConnectionResetError):
                pass
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


def start_http_server():
    server = HTTPServer(("0.0.0.0", HTTP_PORT), MJPEGHandler)
    print(f"[http] MJPEG stream on http://reachy-mini.local:{HTTP_PORT}/")
    server.serve_forever()


# --- Vision loop (visualization only — daemon does the tracking) ------------

def resize_for_inference(frame: np.ndarray, target: int) -> np.ndarray:
    h, w = frame.shape[:2]
    scale = target / max(h, w)
    if scale >= 1.0:
        return frame, 1.0
    return cv2.resize(frame, (int(w * scale), int(h * scale))), scale


def draw_detections(frame: np.ndarray, faces, scale: float,
                    speaker_id: int, labels: list[str],
                    tracked_face_info: str) -> np.ndarray:
    """Draw bounding boxes, landmarks, and annotations on the frame."""
    h, w = frame.shape[:2]
    n = faces.shape[0] if faces is not None else 0

    for i in range(n):
        f = faces[i]
        x = int(f[0] * scale)
        y = int(f[1] * scale)
        bw = int(f[2] * scale)
        bh = int(f[3] * scale)
        is_speaker = (i == speaker_id)
        color = (0, 255, 0) if is_speaker else (0, 200, 255)
        thickness = 3 if is_speaker else 2

        cv2.rectangle(frame, (x, y), (x + bw, y + bh), color, thickness)

        # Draw 5 landmarks (eyes, nose, mouth corners)
        for j in range(5):
            lx = int(f[4 + j * 2] * scale)
            ly = int(f[5 + j * 2] * scale)
            cv2.circle(frame, (lx, ly), 4, color, -1)

        # Label
        label = labels[i] if i < len(labels) else f"face{i}"
        tag = f"{label}{' [SPEAKING]' if is_speaker else ''}"
        cv2.putText(frame, tag, (x, y - 8), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, color, 1, cv2.LINE_AA)

    # HUD
    track_status = "ON (daemon)" if state.tracking_active else "OFF"
    info = (f"FPS: {state.fps:.0f}  |  Faces: {state.n_faces}  |  "
            f"Tracking: {track_status}  |  Speaker: "
            f"face{state.speaker_id if state.speaker_id >= 0 else '-'}")
    cv2.putText(frame, info, (10, 25), cv2.FONT_HERSHEY_SIMPLEX,
                0.6, (0, 255, 0), 2, cv2.LINE_AA)

    if tracked_face_info:
        cv2.putText(frame, tracked_face_info, (10, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (100, 255, 100), 1, cv2.LINE_AA)

    cv2.putText(frame, "Ctrl-C to quit", (10, h - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (150, 150, 150), 1, cv2.LINE_AA)
    return frame


def vision_loop(mini: ReachyMini,
                detector: cv2.FaceDetectorYN,
                recognizer: cv2.FaceRecognizerSF):
    """Capture -> YuNet detect -> annotate -> serve.

    Head tracking is handled by the daemon via start_head_tracking().
    This loop is only for browser visualization.
    """
    mouth_bufs: dict[int, deque] = {}
    known_features: list[np.ndarray] = []
    next_id = 0
    frame_count = 0

    fps_counter = 0
    fps_time = time.time()
    fps = 0.0

    print("[vision] Starting visualization loop...")
    print("[vision] Head tracking is handled by the daemon (start_head_tracking)")

    while state.running:
        t_start = time.perf_counter()

        # --- Capture ---
        frame = mini.media.get_frame()
        if frame is None:
            time.sleep(0.01)
            continue
        if frame.ndim == 3 and frame.shape[2] == 3:
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

        h, w = frame.shape[:2]
        frame_count += 1

        # --- YuNet detection (fast — 26ms at 320px) ---
        resized, scale = resize_for_inference(frame, INFER_SIZE)
        rh, rw = resized.shape[:2]
        detector.setInputSize((rw, rh))
        faces = detect_faces(detector, resized)
        n_faces = faces.shape[0] if faces is not None else 0

        # --- Per-face processing ---
        labels = []
        speaker_id = -1
        best_energy = MOUTH_ENERGY_FLOOR

        if faces is not None and n_faces > 0:
            for i in range(n_faces):
                # --- Mouth energy (cheap — 1.5ms) ---
                aligned = recognizer.alignCrop(resized, faces[i])
                mouth = cv2.cvtColor(aligned[74:112, 28:84], cv2.COLOR_BGR2GRAY)
                mouth = cv2.GaussianBlur(mouth, (5, 5), 0).astype(np.float32) / 255.0
                mouth_bufs.setdefault(i, deque(maxlen=MOUTH_BUF_LEN))
                mouth_bufs[i].append(mouth)
                if len(mouth_bufs[i]) > 5:
                    energy = float(np.mean(np.var(np.stack(mouth_bufs[i]), axis=0)))
                else:
                    energy = 0.0

                if energy > best_energy:
                    best_energy = energy
                    speaker_id = i

                # --- SFace ID (expensive — only every SFACE_INTERVAL frames) ---
                if frame_count % SFACE_INTERVAL == 0:
                    feat = recognizer.feature(aligned)
                    person_id = -1
                    best_sim = 0.5
                    for kid, kf in enumerate(known_features):
                        sim = float(recognizer.match(feat, kf, cv2.FaceRecognizerSF_FR_COSINE))
                        if sim > best_sim:
                            best_sim = sim
                            person_id = kid
                    if person_id == -1:
                        person_id = next_id
                        next_id += 1
                        known_features.append(feat)
                    labels.append(f"person{person_id}")
                else:
                    # Reuse last label if available, else generic
                    labels.append(f"face{i}")

        # --- Read daemon's tracked face for HUD ---
        tracked_info = ""
        try:
            tracked = mini.get_tracked_face(wait=False)
            if tracked is not None:
                tracked_info = f"Daemon tracking: face at ({tracked.cx:.2f}, {tracked.cy:.2f})"
        except Exception:
            pass

        # --- Annotate frame ---
        annotated = frame.copy()
        draw_detections(annotated, faces, scale, speaker_id, labels, tracked_info)

        # --- Encode JPEG ---
        ok, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if ok:
            state.set_frame(buf.tobytes(), fps, n_faces, speaker_id, True)

        # --- FPS counter ---
        fps_counter += 1
        elapsed = time.time() - fps_time
        if elapsed >= 1.0:
            fps = fps_counter / elapsed
            fps_counter = 0
            fps_time = time.time()
            print(f"[vision] {fps:.1f} FPS | {n_faces} faces | "
                  f"speaker=face{speaker_id if speaker_id >= 0 else '-'} | "
                  f"tracking=daemon")

        # --- Pace: target ~30 FPS ---
        dt = time.perf_counter() - t_start
        if dt < 0.033:
            time.sleep(0.033 - dt)


# --- Main -------------------------------------------------------------------

def main() -> int:
    print("=" * 60)
    print("Reachy Mini Live Face Tracking (SDK daemon tracking)")
    print("=" * 60)

    # Download models
    print("Loading models...")
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    download(YUNET_URL, YUNET_PATH)
    download(SFACE_URL, SFACE_PATH)

    detector = cv2.FaceDetectorYN.create(
        str(YUNET_PATH), "", (INFER_SIZE, INFER_SIZE),
        score_threshold=CONF_THRESHOLD,
        nms_threshold=NMS_THRESHOLD,
        top_k=TOP_K,
    )
    recognizer = cv2.FaceRecognizerSF.create(str(SFACE_PATH), "")
    print("  YuNet + SFace loaded")

    # Connect to robot
    print("Connecting to robot...")
    mini = ReachyMini(media_backend="default")
    print("  connected")

    # Wake up
    print("Enabling motors + waking up...")
    mini.enable_motors()
    mini.wake_up()
    time.sleep(1.5)
    print("  awake!")

    # Start daemon-side head tracking — this is the SDK's built-in
    # face tracker. It runs on the daemon at high rate with smooth
    # motion. We just enable it and the robot follows faces on its own.
    print("Starting daemon head tracking...")
    try:
        mini.start_head_tracking(weight=0.6)
        print("  head tracking ON (weight=0.6 — balanced)")
    except Exception as exc:
        print(f"  WARNING: start_head_tracking failed: {exc}")
        print("  The daemon may not have vision support.")
        print("  Falling back to no tracking (visualization only).")

    # Start HTTP server in background
    http_thread = threading.Thread(target=start_http_server, daemon=True)
    http_thread.start()
    print()
    print(f">>> Open this URL in your Mac's browser: http://reachy-mini.local:{HTTP_PORT}/")
    print(">>> The robot's head will smoothly follow your face.")
    print(">>> Press Ctrl-C to quit.")
    print()

    # Run vision loop (visualization only — daemon does the tracking)
    try:
        vision_loop(mini, detector, recognizer)
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        state.running = False
        time.sleep(0.3)

        # Stop head tracking
        print("Stopping head tracking...")
        try:
            mini.stop_head_tracking()
        except Exception:
            pass

        # Go to sleep
        print("Going to sleep...")
        try:
            mini.goto_sleep()
            time.sleep(1.0)
        except Exception:
            pass

        mini.__exit__(None, None, None)
        print("Done.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
