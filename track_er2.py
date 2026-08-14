"""Live webcam object tracker driven by Gemini Robotics ER 2 Streaming.

Uses the Live API for a persistent WebSocket session, enabling real-time
frame streaming and lower-latency detections compared to one-shot calls.

Usage:
    export GEMINI_API_KEY=...
    python track_er2.py                 # asks what to track
    python track_er2.py "red mug"       # tracks immediately

Keys (focus the video window):
    q / ESC   quit
    n         enter a new target in the terminal
    b         toggle bounding boxes
    space     pause / resume inference
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import threading
import time
from dataclasses import dataclass, field

import cv2
from google import genai
from google.genai import types

MODEL = "gemini-robotics-er-2-streaming-preview"
CAMERA_INDEX = 0
INFER_WIDTH = 640  # frames are downscaled to this width before upload
JPEG_QUALITY = 80
SMOOTHING = 0.4  # EMA factor for the tracked point; 0 = frozen, 1 = no smoothing
STALE_AFTER = 2.0  # seconds without a detection before the lock is dropped
FRAME_INTERVAL = 1.0  # Live API rate-limits video to 1 FPS

SYSTEM_INSTRUCTION = (
    "You are a real-time vision-based object tracker. "
    "For each image you receive, locate the requested target and respond "
    "with ONLY a JSON array of detections. No prose, no markdown fences."
)

PROMPT = """Find the {target} in this image.

Return ONLY a JSON array and nothing else - no markdown fences, no prose.
Each element must be:
  {{"label": <short name>, "point": [y, x], "box": [y, x, y2, x2], "confidence": <float 0-1>}}

Coordinates are normalized to 0-1000 in [y, x] order with the origin at the
top-left corner. "point" is the center of the object.
Return at most 3 matches, most confident first.
If the {target} is not visible, return exactly [].
"""


@dataclass
class Detection:
    label: str
    point: tuple[float, float]  # normalized (y, x) in 0-1000
    box: tuple[float, float, float, float] | None
    confidence: float


@dataclass
class TrackState:
    """Shared between the capture loop and the inference worker."""

    target: str
    lock: threading.Lock = field(default_factory=threading.Lock)
    frame: "cv2.Mat | None" = None
    detections: list[Detection] = field(default_factory=list)
    smoothed: tuple[float, float] | None = None
    last_seen: float = 0.0
    latency_ms: float = 0.0
    error: str = ""
    paused: bool = False
    running: bool = True
    send_time: float = 0.0  # when the last frame was sent to the model

    def set_frame(self, frame) -> None:
        with self.lock:
            self.frame = frame

    def get_frame(self):
        with self.lock:
            return None if self.frame is None else self.frame.copy()

    def snapshot(self):
        with self.lock:
            return (list(self.detections), self.smoothed, self.last_seen,
                    self.latency_ms, self.error, self.target)

    def set_target(self, target: str) -> None:
        with self.lock:
            self.target = target
            self.detections = []
            self.smoothed = None
            self.last_seen = 0.0

    def update(self, detections: list[Detection], latency_ms: float, error: str) -> None:
        with self.lock:
            self.detections = detections
            self.latency_ms = latency_ms
            self.error = error
            if detections:
                y, x = detections[0].point
                if self.smoothed is None:
                    self.smoothed = (y, x)
                else:
                    py, px = self.smoothed
                    self.smoothed = (py + SMOOTHING * (y - py), px + SMOOTHING * (x - px))
                self.last_seen = time.time()


def encode_frame_jpeg(frame) -> bytes:
    """Downscale and JPEG-encode a frame, returning raw bytes."""
    h, w = frame.shape[:2]
    if w > INFER_WIDTH:
        scale = INFER_WIDTH / w
        frame = cv2.resize(frame, (INFER_WIDTH, int(h * scale)))
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    return buf.tobytes()


def parse_detections(text: str) -> list[Detection]:
    """Pull a JSON array out of the model reply, tolerating stray markdown."""
    if not text:
        return []
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return []
    try:
        raw = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []

    out: list[Detection] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        point = item.get("point")
        if not (isinstance(point, (list, tuple)) and len(point) == 2):
            continue
        box = item.get("box")
        box = tuple(float(v) for v in box) if isinstance(box, (list, tuple)) and len(box) == 4 else None
        out.append(Detection(
            label=str(item.get("label", "object")),
            point=(float(point[0]), float(point[1])),
            box=box,
            confidence=float(item.get("confidence", 0.0) or 0.0),
        ))
    return out


async def receive_loop(session, state: TrackState) -> None:
    """Receive text from the model, parse detections, update state."""
    buffer = ""
    try:
        async for message in session.receive():
            if not state.running:
                break
            if message.server_content:
                sc = message.server_content
                if sc.model_turn and sc.model_turn.parts:
                    for part in sc.model_turn.parts:
                        if part.text:
                            buffer += part.text
                if sc.turn_complete:
                    latency = (time.time() - state.send_time) * 1000 if state.send_time else 0
                    detections = parse_detections(buffer)
                    state.update(detections, latency, "")
                    if detections:
                        d = detections[0]
                        print(f"[{time.strftime('%H:%M:%S')}] {d.label} at y={d.point[0]:.0f} "
                              f"x={d.point[1]:.0f} conf={d.confidence:.2f}  {latency:.0f}ms")
                    buffer = ""
    except Exception as exc:
        if state.running:
            print(f"[recv error] {exc}", file=sys.stderr)


async def streaming_worker(client: genai.Client, state: TrackState) -> None:
    """Open a persistent Live API session and stream frames for detection."""
    config = types.LiveConnectConfig(
        response_modalities=["TEXT"],
        system_instruction=types.Content(
            parts=[types.Part(text=SYSTEM_INSTRUCTION)]
        ),
    )

    while state.running:
        try:
            async with client.aio.live.connect(model=MODEL, config=config) as session:
                recv_task = asyncio.create_task(receive_loop(session, state))
                print(f"[stream] Connected to {MODEL}")

                while state.running:
                    if state.paused:
                        await asyncio.sleep(0.1)
                        continue

                    frame = state.get_frame()
                    if frame is None:
                        await asyncio.sleep(0.05)
                        continue

                    with state.lock:
                        target = state.target

                    try:
                        jpeg_bytes = encode_frame_jpeg(frame)
                        state.send_time = time.time()
                        await session.send_client_content(
                            turns=types.Content(role="user", parts=[
                                types.Part(inline_data=types.Blob(
                                    data=jpeg_bytes, mime_type="image/jpeg")),
                                types.Part(text=PROMPT.format(target=target)),
                            ]),
                            turn_complete=True,
                        )
                    except Exception as exc:
                        state.update([], 0, str(exc)[:120])
                        print(f"[send error] {exc}", file=sys.stderr)
                        break  # force reconnect

                    await asyncio.sleep(FRAME_INTERVAL)

                recv_task.cancel()
                try:
                    await recv_task
                except asyncio.CancelledError:
                    pass

        except Exception as exc:
            if state.running:
                state.update([], 0, str(exc)[:120])
                print(f"[session error] {exc}", file=sys.stderr)
                await asyncio.sleep(2.0)


def _run_asyncio(coro) -> None:
    """Run an asyncio coroutine in a dedicated event loop (for thread use)."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(coro)


def steering_command(point: tuple[float, float]) -> tuple[float, float]:
    """Map a normalized [y, x] point to (pan, tilt) errors in -1..1.

    This is the hand-off point to a real robot: positive pan means the target is
    to the right of frame center, positive tilt means it is above center.
    """
    y, x = point
    return (x - 500.0) / 500.0, (500.0 - y) / 500.0


def draw_overlay(frame, state: TrackState, show_boxes: bool):
    h, w = frame.shape[:2]
    detections, smoothed, last_seen, latency_ms, error, target = state.snapshot()
    fresh = smoothed is not None and (time.time() - last_seen) < STALE_AFTER

    if show_boxes:
        for det in detections[1:]:
            if det.box:
                y1, x1, y2, x2 = det.box
                cv2.rectangle(frame, (int(x1 / 1000 * w), int(y1 / 1000 * h)),
                              (int(x2 / 1000 * w), int(y2 / 1000 * h)), (120, 120, 120), 1)

    if detections and show_boxes and detections[0].box:
        y1, x1, y2, x2 = detections[0].box
        cv2.rectangle(frame, (int(x1 / 1000 * w), int(y1 / 1000 * h)),
                      (int(x2 / 1000 * w), int(y2 / 1000 * h)), (0, 220, 0), 2)

    if fresh:
        cy, cx = smoothed
        px, py = int(cx / 1000 * w), int(cy / 1000 * h)
        cv2.line(frame, (w // 2, h // 2), (px, py), (0, 220, 0), 1)
        cv2.circle(frame, (px, py), 10, (0, 220, 0), 2)
        cv2.circle(frame, (px, py), 2, (0, 220, 0), -1)
        pan, tilt = steering_command(smoothed)
        label = detections[0].label if detections else target
        cv2.putText(frame, f"{label}  pan={pan:+.2f} tilt={tilt:+.2f}", (px + 14, py - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 220, 0), 1, cv2.LINE_AA)

    cv2.drawMarker(frame, (w // 2, h // 2), (200, 200, 200), cv2.MARKER_CROSS, 14, 1)

    status = "PAUSED" if state.paused else ("LOCKED" if fresh else "SEARCHING")
    color = (0, 220, 0) if fresh and not state.paused else (0, 200, 255)
    cv2.putText(frame, f"target: {target}   [{status}]   {latency_ms:.0f} ms",
                (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)
    cv2.putText(frame, "q quit   n new target   b boxes   space pause",
                (10, h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1, cv2.LINE_AA)
    if error:
        cv2.putText(frame, error, (10, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                    (60, 60, 255), 1, cv2.LINE_AA)
    return frame


def main() -> int:
    if not os.environ.get("GEMINI_API_KEY"):
        print("Set GEMINI_API_KEY first:  export GEMINI_API_KEY=...", file=sys.stderr)
        return 1

    target = " ".join(sys.argv[1:]).strip() or input("What should I track? ").strip()
    if not target:
        print("No target given.", file=sys.stderr)
        return 1

    camera = cv2.VideoCapture(CAMERA_INDEX)
    if not camera.isOpened():
        print(f"Could not open camera {CAMERA_INDEX}. On macOS, grant camera access to "
              "your terminal in System Settings > Privacy & Security > Camera.", file=sys.stderr)
        return 1

    state = TrackState(target=target)
    client = genai.Client()
    worker = threading.Thread(
        target=_run_asyncio,
        args=(streaming_worker(client, state),),
        daemon=True,
    )
    worker.start()
    print(f"Tracking '{target}' with {MODEL} (streaming). Focus the window and press q to quit.")

    show_boxes = True
    try:
        while True:
            ok, frame = camera.read()
            if not ok:
                print("Dropped frame from camera.", file=sys.stderr)
                break
            frame = cv2.flip(frame, 1)  # mirror so movement feels natural
            state.set_frame(frame)
            cv2.imshow("Gemini Robotics ER 2 tracker", draw_overlay(frame.copy(), state, show_boxes))

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord("b"):
                show_boxes = not show_boxes
            if key == ord(" "):
                state.paused = not state.paused
            if key == ord("n"):
                new_target = input("New target: ").strip()
                if new_target:
                    state.set_target(new_target)
                    print(f"Now tracking '{new_target}'.")
    except KeyboardInterrupt:
        pass
    finally:
        state.running = False
        camera.release()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
