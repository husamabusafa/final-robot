"""main_pi.py - Reachy Mini runtime for the wireless Pi (lightweight stack).

This is a Pi-compatible rewrite of main.py that replaces:
  - YOLOv8-Pose + torch  ->  YuNet (230KB ONNX) for face detection
  - FaceNet + torch      ->  SFace (37MB ONNX) for face recognition
  - MediaPipe head pose  ->  disabled (not needed on Pi)
  - MediaPipe gestures   ->  disabled (not needed on Pi)
  - SileroVAD + torch    ->  disabled (mouth-energy only)
  - SpeechBrain voice ID ->  disabled
  - cv2.VideoCapture      ->  mini.media.get_frame() (daemon camera)
  - cv2.imshow           ->  MJPEG stream on http://reachy-mini.local:8080/
  - CascadeTracker       ->  daemon start_head_tracking() (smooth, built-in)

Keeps:
  - Gemini Live voice/vision (gemini_live.py — no torch deps)
  - All Gemini tools (head movement, face enroll/identify, etc.)
  - Mouth-energy speaker detection (cheap, no torch)

Animation is SDK-native:
  - Speaking     ->  mini.enable_wobbling() (audio-reactive 6-DOF head sway,
                     composed daemon-side before IK, so it never fights
                     daemon head tracking)
  - Expressions  ->  reachy-mini-emotions-library via play_move()
  - Antennas     ->  minimal idle breathe (no SDK equivalent exists)

Run on the Pi:
    source /venvs/apps_venv/bin/activate
    pip install google-genai python-dotenv scipy
    python /home/pollen/main_pi.py

Press Ctrl-C to quit.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from collections import deque
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Dict, Optional

import cv2
import numpy as np
from dotenv import load_dotenv
from google import genai
from google.genai import types as genai_types
from reachy_mini import ReachyMini
from reachy_mini.utils import create_head_pose

# Reuse the existing Gemini Live session wrapper (no torch deps)
from hsafa_robot.gemini_live import GeminiLiveSession
from hsafa_robot.panel_client import PanelClient

log = logging.getLogger("hsafa_robot.main_pi")


# --- Antenna idle breathe ----------------------------------------------------

class AntennaBreather:
    """Slow antenna "breathe" so the robot never looks switched off.

    Deliberately minimal. Speaking expressiveness is the SDK's job -- the
    audio-reactive wobbler (``mini.enable_wobbling()``) drives the head from
    the actual speaker output, and the emotions library drives whole-body
    clips. The antennas are the one channel the SDK has no animation for, so
    this is all that stays hand-rolled.
    """

    BASE_DEG = -8.0
    AMPL_DEG = 3.0
    FREQ_HZ = 0.22

    def __init__(self):
        self.t0 = time.time()

    def tick(self) -> tuple:
        """Return (right_ant_rad, left_ant_rad) for the current moment."""
        t = time.time() - self.t0
        breath = math.sin(2.0 * math.pi * self.FREQ_HZ * t)
        base = math.radians(self.BASE_DEG)
        wiggle = math.radians(self.AMPL_DEG) * breath
        return (base + wiggle, base - wiggle)


# --- Emotions (SDK recorded-move library) ------------------------------------

class EmotionPlayer:
    """Plays clips from the SDK's recorded-move library.

    Playback evaluates the clip at 100 Hz and drives head, antennas and
    body_yaw directly, so it *owns* the robot for the clip's duration. While
    a clip runs we pause daemon head tracking and mute the antenna breathe
    loop (via :attr:`is_playing`) so nothing fights it. Clips carry a sidecar
    sound which the SDK plays for us.
    """

    LIBRARY = "pollen-robotics/reachy-mini-emotions-library"

    def __init__(self, mini):
        self._mini = mini
        self._moves = None
        self._names: list[str] = []
        self.is_playing = threading.Event()

    def load(self) -> bool:
        """Load the library. The daemon preloads it at startup, so this is
        normally a cache hit; falls back to a network download."""
        try:
            from reachy_mini.motion.recorded_move import RecordedMoves
            self._moves = RecordedMoves(self.LIBRARY)
            self._names = sorted(self._moves.list_moves())
            return True
        except Exception as exc:
            log.warning("emotions library unavailable: %s", exc)
            self._moves = None
            self._names = []
            return False

    @property
    def names(self) -> list[str]:
        return list(self._names)

    async def play(
        self, name: str, track_weight: float, resume_tracking: bool = True,
    ) -> dict:
        """Play a clip, pausing head tracking for its duration.

        Args:
            track_weight: Weight to restore head tracking with afterwards.
            resume_tracking: False when the caller had face-follow switched
                off on purpose (``disable_face_follow``), so the clip does
                not silently turn it back on.
        """
        if self._moves is None:
            return {"ok": False, "error": "emotions library not loaded"}
        if name not in self._names:
            return {"ok": False, "error": f"unknown emotion: {name}"}
        if self.is_playing.is_set():
            # Interrupt whatever is playing rather than layering two clips.
            self._mini.cancel_move()
            await asyncio.sleep(0.05)

        move = self._moves.get(name)
        self.is_playing.set()
        try:
            self._mini.stop_head_tracking()
        except Exception:
            pass
        try:
            await self._mini.async_play_move(move, initial_goto_duration=0.4)
        except Exception as exc:
            log.warning("play_move(%s) failed: %s", name, exc)
            return {"ok": False, "error": str(exc)}
        finally:
            self.is_playing.clear()
            if resume_tracking:
                try:
                    self._mini.start_head_tracking(weight=track_weight)
                except Exception:
                    pass
        return {"ok": True, "emotion": name, "duration_s": round(move.duration, 2)}


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

# --- Presentation panel -----------------------------------------------------
# The screen lives in a deployed web app (see panel/). The robot connects out to
# it as a WebSocket publisher, so it works from any network without port
# forwarding. Unset PANEL_URL to run fully offline on the local :8080 page.
# Read in main() after load_dotenv(), e.g. PANEL_URL=wss://panel.example.com/robot
PANEL_URL = ""
PANEL_TOKEN = ""

# Tile ceiling, mirrored in panel/shared/protocol.ts: more than six tiles on one
# screen is unreadable from across a room.
MAX_TILES = 6

# Per-type item limits, chosen so a tile never renders cramped.
TILE_TYPES = ("kpi", "bar", "pie", "line", "table", "map")
TILE_MAX_ITEMS = {"kpi": 6, "bar": 8, "pie": 6, "line": 12, "table": 6, "map": 8}

# SFace runs every N frames for ID (120ms is too slow per-frame)
SFACE_INTERVAL = 15

# Mouth energy config
MOUTH_BUF_LEN = 15
MOUTH_ENERGY_FLOOR = 0.002

# Head tracking
TRACK_WEIGHT = 0.6  # daemon head tracking weight (0-1)

FACE_DB_DIR = Path(__file__).resolve().parent / "data" / "faces"
FACE_DB_DIR.mkdir(parents=True, exist_ok=True)

# --- System instruction (Pi persona; main.py has its own older one) ---------

DEFAULT_SYSTEM_INSTRUCTION = (
    "You are a small, warm, curious desk robot embodied in "
    "Reachy Mini. You see through the camera, hear through the "
    "microphone, and speak through the robot's speaker. Talk like a "
    "friendly companion, not an assistant.\n"
    "\n"
    "IDENTITY\n"
    "- You have no name. Never invent one.\n"
    "- You are Rafed's robot companion. Rafed (رافد) is Tatweer "
    "Holding's school-transport company -- the Ministry of "
    "Education's executive arm for school transport, safely carrying "
    "more than 740,000 students to school every day across all 13 "
    "regions of Saudi Arabia.\n"
    "- Your role: welcome visitors, introduce Rafed and its services, "
    "answer school-transport questions from your knowledge base "
    "below, and show Rafed videos and live dashboards on the screen. "
    "You are yourself a live example of Rafed's digital "
    "transformation.\n"
    "- When introducing yourself, briefly explain who you are and "
    "what you can do, in your own words -- no fixed script.\n"
    "\n"
    "LANGUAGE\n"
    "- Arabic is your primary language: always open in Arabic and use "
    "it by default.\n"
    "- If a person speaks to you in English, switch to natural, warm "
    "English for as long as they speak English. If they switch back "
    "to Arabic, switch back to Arabic. Any other language: answer in "
    "Arabic.\n"
    "- Never mix the two in one sentence.\n"
    "- Arabic style: plain Modern Standard Arabic (فصحى), spoken "
    "naturally -- no regional accent and no dialect words. Warm and "
    "conversational, not stiff or formal like a newsreader.\n"
    "\n"
    "STYLE\n"
    "- Speak naturally and keep replies short -- usually one or two "
    "sentences. Expand only when a question genuinely needs more "
    "detail. No lists, no preamble, no filler.\n"
    "- Never narrate your own actions. Call the tool and react as if "
    "it just happened. Never ask permission to use a tool.\n"
    "\n"
    "MOVEMENT (face-follow is ON by default; look_* and set_head_angle "
    "auto-release back to tracking after a couple of seconds)\n"
    "- \"look left/right/up/down/straight\": matching `look_*` preset; "
    "specific angles: `set_head_angle(yaw, pitch)`.\n"
    "- \"stop following\": `disable_face_follow()`; \"follow me\": "
    "`enable_face_follow()`.\n"
    "- SEARCHING: when asked to find something, search silently: look "
    "in one direction, check the camera, then immediately call the "
    "next movement tool. Never ask between steps, never speak "
    "mid-search. Speak only after finding it or after all directions "
    "failed.\n"
    "\n"
    "BODY LANGUAGE\n"
    "- Your head already sways naturally while you speak -- never "
    "mention it and never try to animate it yourself.\n"
    "- For a genuine emotional beat, call `play_emotion(name)` with "
    "one of the names listed in that tool's description. Use it "
    "sparingly -- a few times per conversation at most, only when "
    "the feeling is real, never as punctuation.\n"
    "\n"
    "PEOPLE / FACES\n"
    "- Introduction (\"I'm X\"): `enroll_face` with the name.\n"
    "- \"who am I / who do you see\": `identify_person`. \"is X "
    "here?\": `find_person(name)`. \"who do you remember\": "
    "`list_known_people`. \"who is talking\": `who_is_speaking`.\n"
    "- \"what do you see?\": `describe_scene`, then summarise.\n"
    "\n"
    "\n"
    "SCREEN (a presentation screen is open next to you and shows what you "
    "choose)\n"
    "- \"show/play the X video\": `show_content(\"<what>\")` -- company "
    "videos from the Tatweer group catalog (videos only, no websites).\n"
    "- \"show stats / numbers / a chart\": build a dashboard with "
    "`add_tile` -- ONE tile per call, 3-4 calls back to back, no "
    "talking in between, then one short spoken sentence.\n"
    "- \"where is X? / show me on the map\": add_tile(type=\"map\") "
    "with latitude+longitude+zoom (16 for a building, 12 for a "
    "city), or markers=[{label,latitude,longitude},...] for several "
    "pins. Rafed HQ: 24.7679888, 46.665489.\n"
    "- Pass `dashboard_title` on the FIRST tile only. If the topic "
    "changes and the screen should switch to a NEW dashboard, call "
    "`clear_display()` first, then add tiles -- dashboard_title "
    "alone never removes tiles.\n"
    "- Values are plain numbers (740000), never text (\"740 ألف\"). "
    "Use only numbers you actually know from the company knowledge "
    "below -- never invent them.\n"
    "- \"clear/hide the screen\": `clear_display()`.\n"
    "- Offer to show a chart or video when it would genuinely help -- "
    "not in every reply. Call the tool only after the user agrees.\n"
    "\n"
    "TOOLS\n"
    "- Use a tool whenever it provides information or actions you "
    "cannot reliably do yourself. Casual chat needs no tools -- "
    "just chat. After a tool call, respond naturally with the "
    "result.\n"
)


# --- Company knowledge base -------------------------------------------------
# Loaded at startup and appended to the system instruction so Gemini can
# answer questions. Rafed-focused (rafed_knowledge.md); the old group-wide
# file is kept for reference but not loaded.
COMPANY_KB_PATH = (
    Path(__file__).resolve().parent / "rafed_knowledge.md"
)


def load_company_knowledge(path: Path = COMPANY_KB_PATH) -> str:
    """Read the company KB markdown; return '' if missing/unreadable."""
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError as e:
        print(f"  WARNING: company KB not loaded ({e})")
        return ""
    return text


# --- URL catalog (presentation screen content) ----------------------------
# urls.json: list of {id, company, title, type ("video"|"page"), url,
# keywords}. Loaded once at startup; the show_content tool searches it.
URLS_PATH = Path(__file__).resolve().parent / "urls.json"


def load_url_catalog(path: Path = URLS_PATH) -> list:
    """Read the URL catalog; return [] if missing/broken."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"  WARNING: url catalog not loaded ({e})")
        return []
    return data if isinstance(data, list) else []


def find_url_entry(catalog: list, query: str):
    """Best keyword match for a free-text query over the catalog."""
    q = (query or "").strip().lower()
    if not q:
        return None
    best = None
    best_score = 0
    for e in catalog:
        hay = " ".join(
            [str(e.get("id", "")), str(e.get("company", "")),
             str(e.get("title", ""))]
            + [str(k) for k in e.get("keywords", [])]
        ).lower()
        score = sum(1 for tok in q.split() if tok and tok in hay)
        if q in hay:
            score += 3
        if score > best_score:
            best, best_score = e, score
    return best if best_score > 0 else None


# --- Tile normalisation -----------------------------------------------------
# Gemini gets numbers slightly wrong in predictable ways: "740,000", "740 ألف",
# "1.2M", strings instead of numbers, arrays of unequal length. Repairing the
# arguments here keeps the conversation flowing -- an error return makes the
# model apologise out loud mid-presentation, which is worse than a rounded value.

_SCALE_WORDS = {
    "الف": 1e3, "ألف": 1e3, "آلاف": 1e3, "الاف": 1e3, "k": 1e3,
    "مليون": 1e6, "ملايين": 1e6, "m": 1e6, "mn": 1e6,
    "مليار": 1e9, "مليارات": 1e9, "b": 1e9, "bn": 1e9,
}

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def coerce_number(raw) -> Optional[float]:
    """Best-effort number out of whatever the model sent. None if hopeless."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw) if math.isfinite(float(raw)) else None

    text = str(raw).translate(_ARABIC_DIGITS).strip()
    if not text:
        return None
    text = text.replace(",", "").replace("٫", ".").replace("%", "")

    scale = 1.0
    for word, mult in _SCALE_WORDS.items():
        # Suffix match only, so "مليون" in a label can't inflate a bare number.
        if text.lower().endswith(word):
            scale = mult
            text = text[: -len(word)].strip()
            break

    m = re.search(r"-?\d+(?:\.\d+)?", text)
    if not m:
        return None
    try:
        return float(m.group()) * scale
    except ValueError:
        return None


def normalize_map_tile(args: dict, labels: list) -> tuple[Optional[dict], str]:
    """Validate a map tile: pins and/or a centre, nothing else needed."""
    markers = []
    for m in (args.get("markers") or [])[: TILE_MAX_ITEMS["map"]]:
        if not isinstance(m, dict):
            continue
        lat = coerce_number(m.get("latitude", m.get("lat")))
        lng = coerce_number(m.get("longitude", m.get("lng")))
        if lat is None or lng is None:
            continue
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            continue
        markers.append({
            "label": str(m.get("label", "")).strip(),
            "lat": lat,
            "lng": lng,
        })

    lat = coerce_number(args.get("latitude"))
    lng = coerce_number(args.get("longitude"))
    center = [lng, lat] if lat is not None and lng is not None else None

    if not markers and center is None:
        return None, "map needs markers[] (each with label, latitude, longitude) or latitude+longitude"

    tile = {
        "id": f"t{int(time.time() * 1000)}",
        "type": "map",
        "title": str(args.get("title", "")).strip() or "الخريطة",
        "labels": labels,
        "values": [],
    }
    if markers:
        tile["markers"] = markers
    if center is not None:
        tile["center"] = center
    zoom = coerce_number(args.get("zoom"))
    if zoom is not None and 0 <= zoom <= 20:
        tile["zoom"] = zoom
    return tile, ""


def normalize_tile(args: dict) -> tuple[Optional[dict], str]:
    """Turn raw add_tile arguments into a valid tile.

    Returns (tile, note). `tile` is None only when the request is unusable.
    """
    tile_type = str(args.get("type", "")).strip().lower()
    # Common near-misses from the model.
    tile_type = {
        "stat_grid": "kpi", "stats": "kpi", "number": "kpi", "numbers": "kpi",
        "doughnut": "pie", "donut": "pie", "column": "bar", "trend": "line",
        "area": "line", "list": "table",
    }.get(tile_type, tile_type)
    if tile_type not in TILE_TYPES:
        return None, f"type must be one of {', '.join(TILE_TYPES)}"

    labels = args.get("labels") or []
    if not isinstance(labels, list) or not labels:
        if tile_type != "map":
            return None, "labels must be a non-empty array"
        labels = []
    labels = [str(x).strip() for x in labels if str(x).strip()]
    if not labels and tile_type != "map":
        return None, "labels must be a non-empty array"

    if tile_type == "map":
        return normalize_map_tile(args, labels)

    notes = []
    text_values = args.get("text_values")
    if tile_type == "table" and isinstance(text_values, list) and text_values:
        values_out, texts_out = [], [str(x) for x in text_values]
        n = min(len(labels), len(texts_out))
        if len(labels) != len(texts_out):
            notes.append("labels and text_values had different lengths; extras ignored")
        labels, texts_out = labels[:n], texts_out[:n]
    else:
        raw_values = args.get("values") or []
        if not isinstance(raw_values, list):
            raw_values = []
        if len(raw_values) != len(labels):
            notes.append(
                f"labels ({len(labels)}) and values ({len(raw_values)}) had "
                "different lengths; extras ignored"
            )
        parsed = [coerce_number(v) for v in raw_values]
        # Drop positions we couldn't read at all, keeping labels aligned.
        pairs = [(l, v) for l, v in zip(labels, parsed) if v is not None]
        if not pairs:
            return None, "values must be an array of numbers"
        if len(pairs) != min(len(labels), len(raw_values)):
            notes.append("some values were unreadable and were dropped")
        labels = [p[0] for p in pairs]
        values_out = [p[1] for p in pairs]
        texts_out = None

    limit = TILE_MAX_ITEMS[tile_type]
    if len(labels) > limit:
        notes.append(f"showing the first {limit} items ({tile_type} fits {limit})")
        labels = labels[:limit]
        values_out = values_out[:limit]
        if texts_out is not None:
            texts_out = texts_out[:limit]

    tile = {
        "id": f"t{int(time.time() * 1000)}",
        "type": tile_type,
        "title": str(args.get("title", "")).strip() or "بيانات",
        "labels": labels,
        "values": values_out,
    }
    if texts_out is not None:
        # camelCase: this key goes straight onto the wire (see protocol.ts).
        tile["textValues"] = texts_out
    unit = str(args.get("unit", "")).strip()
    if unit:
        tile["unit"] = unit
    return tile, "; ".join(notes)


def set_full_volume() -> None:
    """Push every playback mixer control to 100% (voice was too low at 62%)."""
    try:
        out = subprocess.run(
            ["amixer", "scontrols"], capture_output=True, text=True, timeout=5
        ).stdout
        names = re.findall(r"Simple mixer control '([^']+)'", out)
        targets = [
            n for n in names
            if n.lower() in ("master", "pcm", "speaker", "headphone")
        ] or ["Master"]
        for n in targets:
            subprocess.run(
                ["amixer", "sset", n, "100%", "unmute"],
                capture_output=True, timeout=5,
            )
        print(f"  Speaker volume -> 100% ({', '.join(targets)})")
    except Exception as e:
        print(f"  WARNING: could not set volume: {e}")


def build_system_instruction() -> str:
    """Base instruction + company knowledge + showable-content list."""
    instruction = DEFAULT_SYSTEM_INSTRUCTION
    kb = load_company_knowledge()
    if kb:
        instruction += (
            "\nCOMPANY KNOWLEDGE\n"
            "You speak for Rafed (رافد) first. When asked about Rafed, "
            "school transport, the fleet, safety, or numbers, answer ONLY "
            "from the facts below, in short spoken Arabic. The other "
            "Tatweer group companies are context only -- mention them "
            "briefly if asked, but always bring the conversation back to "
            "Rafed. If a fact is not listed, say you don't have that "
            "information instead of guessing.\n\n"
            + kb
            + "\n"
        )
    catalog = load_url_catalog()
    if catalog:
        videos = [str(e.get("title", "")) for e in catalog
                  if e.get("type") == "video"]
        pages = [str(e.get("title", "")) for e in catalog
                 if e.get("type") == "page"]
        instruction += (
            "\nCONTENT YOU CAN SHOW ON THE SCREEN (via show_content)\n"
            "Videos: " + " | ".join(videos) + "\n"
            "Pages/sites: " + " | ".join(pages) + "\n"
            "Only offer content from this list.\n"
        )
    return instruction


# --- Model download ---------------------------------------------------------

def download(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  downloading {dest.name}...")
    urllib.request.urlretrieve(url, str(dest))


# Lock for thread-safe YuNet access (vision loop + tool handler share it)
_DETECTOR_LOCK = threading.Lock()


def detect_faces(detector: cv2.FaceDetectorYN, frame: np.ndarray,
                 input_size: Optional[tuple] = None):
    """YuNet detect, handling OpenCV 4.x and 5.x return formats.
    Thread-safe via _DETECTOR_LOCK."""
    with _DETECTOR_LOCK:
        if input_size is not None:
            detector.setInputSize(input_size)
        result = detector.detect(frame)
    if isinstance(result, tuple):
        return result[1]
    return result


def resize_for_inference(frame: np.ndarray, target: int):
    h, w = frame.shape[:2]
    scale = target / max(h, w)
    if scale >= 1.0:
        return frame, 1.0
    return cv2.resize(frame, (int(w * scale), int(h * scale))), scale


# --- Simple face DB (JSON-based, replaces FaceNet+FaceDB) -------------------

class SimpleFaceDB:
    """JSON-backed face database using SFace 128-d embeddings."""

    def __init__(self, db_dir: Path):
        self.db_dir = db_dir
        self.db_file = db_dir / "sface_db.json"
        self.data: Dict[str, list] = {}  # name -> list of 128-d vectors
        self._load()

    def _load(self):
        if self.db_file.exists():
            try:
                raw = json.loads(self.db_file.read_text())
                self.data = {k: [np.array(v, dtype=np.float32) for v in vs]
                             for k, vs in raw.items()}
            except Exception:
                self.data = {}

    def _save(self):
        serializable = {k: [v.tolist() for v in vs] for k, vs in self.data.items()}
        self.db_file.write_text(json.dumps(serializable))

    def list_names(self) -> list[str]:
        return list(self.data.keys())

    def add(self, name: str, embedding: np.ndarray):
        name = name.lower().strip()
        if name not in self.data:
            self.data[name] = []
        self.data[name].append(embedding)
        self._save()

    def identify(self, embedding: np.ndarray, recognizer: cv2.FaceRecognizerSF,
                 threshold: float = 0.5) -> Optional[str]:
        best_name = None
        best_sim = threshold
        for name, vectors in self.data.items():
            for v in vectors:
                sim = float(recognizer.match(embedding, v, cv2.FaceRecognizerSF_FR_COSINE))
                if sim > best_sim:
                    best_sim = sim
                    best_name = name
        return best_name


# --- Shared state -----------------------------------------------------------

class AppState:
    def __init__(self):
        self.lock = threading.Lock()
        self.latest_jpeg: bytes = b""
        self.running = True
        self.fps = 0.0
        self.n_faces = 0
        self.speaker_id = -1
        self.face_labels: list[str] = []
        self.tracking_active = False
        self.gemini_connected = False
        self.gemini_speaking = False
        # Presentation screen state. This is the source of truth; the deployed
        # panel is a projection of it, replayed in full on every reconnect.
        self.display_tiles: list = []
        self.display_title = ""
        self.display_video_url = ""
        self.display_video_title = ""
        self.display_mode = ""  # "" | "dashboard" | "video"
        self.panel = None  # PanelClient, attached in main()

    # --- panel plumbing ---

    def attach_panel(self, client) -> None:
        self.panel = client

    def _emit(self, event: dict) -> None:
        """Push one event to the panel; never let the screen break the robot."""
        panel = self.panel
        if panel is None:
            return
        try:
            panel.emit(event)
        except Exception:
            pass

    def snapshot_events(self) -> list:
        """Current state as a replayable event list (used on panel reconnect)."""
        with self.lock:
            mode, title = self.display_mode, self.display_title
            tiles = list(self.display_tiles)
            url, vtitle = self.display_video_url, self.display_video_title
            speaking = self.gemini_speaking
        events = [{"type": "robot.status", "online": True, "speaking": speaking}]
        if mode == "video" and url:
            events.append({"type": "video.show", "url": url, "title": vtitle})
        elif mode == "dashboard":
            events.append({"type": "dashboard.begin", "title": title})
            events += [{"type": "dashboard.tile", "tile": t} for t in tiles]
        else:
            events.append({"type": "display.clear"})
        return events

    # --- display mutations ---

    def begin_dashboard(self, title: str) -> None:
        with self.lock:
            self.display_mode = "dashboard"
            self.display_title = title
            self.display_tiles = []
            self.display_video_url = ""
            self.display_video_title = ""
        self._emit({"type": "dashboard.begin", "title": title})

    def add_tile(self, tile: dict) -> int:
        """Append one tile. Returns the tile count after the append."""
        with self.lock:
            if self.display_mode != "dashboard":
                self.display_mode = "dashboard"
                self.display_tiles = []
                self.display_video_url = ""
                self.display_video_title = ""
            self.display_tiles.append(tile)
            # Same ceiling the panel enforces, so both ends agree on what's shown.
            if len(self.display_tiles) > MAX_TILES:
                self.display_tiles = self.display_tiles[-MAX_TILES:]
            count = len(self.display_tiles)
        self._emit({"type": "dashboard.tile", "tile": tile})
        return count

    def clear_display(self) -> None:
        with self.lock:
            self.display_tiles = []
            self.display_title = ""
            self.display_video_url = ""
            self.display_video_title = ""
            self.display_mode = ""
        self._emit({"type": "display.clear"})

    def set_video(self, url: str, title: str = "") -> None:
        with self.lock:
            self.display_mode = "video"
            self.display_video_url = url
            self.display_video_title = title
            self.display_tiles = []
        self._emit({"type": "video.show", "url": url, "title": title})

    def set_speaking(self, speaking: bool) -> None:
        """Called every vision frame; only forwards actual transitions."""
        if speaking == self.gemini_speaking:
            return
        self.gemini_speaking = speaking
        self._emit({"type": "robot.status", "online": True, "speaking": speaking})

    def get_display(self) -> dict:
        """State for the local fallback page on :8080 (no internet needed)."""
        with self.lock:
            if self.display_mode == "video":
                return {"type": "video", "url": self.display_video_url,
                        "title": self.display_video_title}
            if self.display_mode == "dashboard":
                return {"type": "dashboard", "title": self.display_title,
                        "tiles": self.display_tiles}
            return {"type": "", "url": "", "title": "", "tiles": []}

    def set_frame(self, jpeg: bytes, **kwargs):
        with self.lock:
            self.latest_jpeg = jpeg
            for k, v in kwargs.items():
                setattr(self, k, v)

    def get_frame(self) -> bytes:
        with self.lock:
            return self.latest_jpeg


state = AppState()


# --- HTTP MJPEG server ------------------------------------------------------

# Local fallback screen: http://<robot>:8080/display
#
# The real presentation screen is the deployed panel (see panel/). This page
# exists only for demos with no internet: deliberately dependency-free -- no
# CDN fonts, no chart library -- because those are exactly what fail offline.
DISPLAY_HTML = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>شاشة العرض (محلي)</title>
<style>
*{box-sizing:border-box}
body{margin:0;height:100vh;background:#0a0e1a;color:#e6edf3;overflow:hidden;
font-family:system-ui,-apple-system,"Segoe UI",sans-serif}
#wrap{height:100vh;display:flex;flex-direction:column}
h1{font-size:28px;font-weight:800;margin:0;padding:18px;text-align:center;
border-bottom:1px solid #1e293b;color:#5ea3f7}
#grid{flex:1;display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));
gap:14px;padding:16px;overflow:auto;align-content:start}
.tile{background:#151c2e;border:1px solid #1e293b;border-radius:14px;padding:16px}
.tile h2{font-size:17px;margin:0 0 12px;color:#5ea3f7;font-weight:700}
.row{display:flex;justify-content:space-between;gap:10px;padding:6px 0;
border-bottom:1px solid #16202f;font-size:16px}
.row b{font-variant-numeric:tabular-nums;color:#a78bfa}
#idle{flex:1;display:flex;flex-direction:column;align-items:center;
justify-content:center;text-align:center;padding:0 8vw}
#idle p{color:#8b98a9;font-size:20px;line-height:1.8}
iframe{width:100%;height:100vh;border:0;background:#000;display:none}
</style></head>
<body>
<div id="wrap">
  <h1 id="title">شاشة العرض</h1>
  <div id="grid"></div>
  <div id="idle"><p>في انتظار المحتوى…</p></div>
</div>
<iframe id="video" allow="autoplay; encrypted-media; fullscreen" allowfullscreen></iframe>
<script>
const $ = (id) => document.getElementById(id);
let last = null;

function fmt(n){
  const a = Math.abs(n);
  if(a >= 1e9) return (n/1e9).toFixed(1).replace(/\.0$/,"") + " مليار";
  if(a >= 1e6) return (n/1e6).toFixed(1).replace(/\.0$/,"") + " مليون";
  if(a >= 1e3) return (n/1e3).toFixed(1).replace(/\.0$/,"") + " ألف";
  return String(Math.round(n));
}

function embed(url){
  try{
    const u = new URL(url);
    const id = u.hostname.includes("youtu.be") ? u.pathname.slice(1)
             : u.searchParams.get("v");
    return id ? "https://www.youtube-nocookie.com/embed/" + id + "?autoplay=1&rel=0" : url;
  }catch(e){ return url; }
}

function render(d){
  const isVideo = d.type === "video" && d.url;
  $("video").style.display = isVideo ? "block" : "none";
  $("wrap").style.display = isVideo ? "none" : "flex";
  if(isVideo){ $("video").src = embed(d.url); return; }
  $("video").src = "about:blank";

  const tiles = d.tiles || [];
  $("title").textContent = d.title || "شاشة العرض";
  $("idle").style.display = tiles.length ? "none" : "flex";
  $("grid").innerHTML = tiles.map(t => {
    const rows = t.labels.map((label, i) => {
      const v = t.textValues ? t.textValues[i]
              : fmt(t.values[i] || 0) + (t.unit ? " " + t.unit : "");
      return `<div class="row"><span>${label}</span><b>${v}</b></div>`;
    }).join("");
    return `<div class="tile"><h2>${t.title || ""}</h2>${rows}</div>`;
  }).join("");
}

async function poll(){
  try{
    const r = await fetch("/api/display", {cache:"no-store"});
    const d = await r.json();
    const s = JSON.stringify(d);
    if(s !== last){ last = s; render(d); }
  }catch(e){}
  setTimeout(poll, 800);
}
poll();
</script>
</body></html>"""


class MJPEGHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            html = (
                "<!DOCTYPE html><html><head><title>Hsafa Robot</title>"
                "<style>body{margin:0;background:#111;display:flex;"
                "flex-direction:column;align-items:center;justify-content:center;"
                "height:100vh;font-family:monospace;color:#0f0}"
                "img{max-width:90vw;max-height:80vh;border:2px solid #0f0}"
                "h2{margin:10px}</style></head>"
                "<body><h2>Hsafa - Reachy Mini (Pi)</h2>"
                f"<img src='/stream' alt='stream'></body></html>"
            )
            self.wfile.write(html.encode())
        elif self.path == "/display":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(DISPLAY_HTML.encode("utf-8"))
        elif self.path == "/api/display":
            payload = json.dumps(state.get_display(), ensure_ascii=False)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(payload.encode("utf-8"))
        elif self.path == "/stream":
            self.send_response(200)
            self.send_header("Age", "0")
            self.send_header("Cache-Control", "no-cache, private")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Type",
                             "multipart/x-mixed-replace; boundary=FRAME")
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
                    time.sleep(0.033)
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


# --- LatestFrame (for Gemini) -----------------------------------------------

class LatestFrame:
    def __init__(self, jpeg_quality: int = 70):
        self._lock = threading.Lock()
        self._frame: Optional[np.ndarray] = None
        self._jpeg_quality = jpeg_quality

    def set(self, frame: np.ndarray):
        with self._lock:
            self._frame = frame

    def get_frame(self) -> Optional[np.ndarray]:
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def get_jpeg(self) -> Optional[bytes]:
        with self._lock:
            frame = self._frame
        if frame is None:
            return None
        ok, buf = cv2.imencode(".jpg", frame,
                               [int(cv2.IMWRITE_JPEG_QUALITY), self._jpeg_quality])
        return buf.tobytes() if ok else None

    def get_mirrored_jpeg(self) -> Optional[bytes]:
        with self._lock:
            frame = self._frame
        if frame is None:
            return None
        mirrored = cv2.flip(frame, 1)
        ok, buf = cv2.imencode(".jpg", mirrored,
                               [int(cv2.IMWRITE_JPEG_QUALITY), self._jpeg_quality])
        return buf.tobytes() if ok else None


# --- Tool builders (same interface as main.py) ------------------------------

# Curated conversational subset of the emotions library. The full library
# ships 85 clips (dances, death throes, sleep...) which would just be noise
# in a tool schema, so we advertise the ones that map to a conversational
# beat. Intersected with what the library actually contains at runtime.
EMOTION_CHOICES: dict[str, str] = {
    "welcoming1": "greeting someone / saying hello",
    "cheerful1": "happy, upbeat",
    "enthusiastic1": "excited, eager",
    "curious1": "curious about something",
    "inquiring1": "asking a question",
    "attentive1": "listening closely",
    "surprised1": "mild surprise",
    "amazed1": "strong amazement / wow",
    "proud1": "proud of an achievement",
    "grateful1": "thanking someone",
    "laughing1": "laughing at something funny",
    "thoughtful1": "thinking / considering",
    "confused1": "confused, did not understand",
    "uncertain1": "unsure, hesitant",
    "understanding1": "acknowledging, 'I see'",
    "sad1": "sad, disappointed",
    "oops1": "made a mistake / apologising",
    "relief1": "relieved",
    "success1": "celebrating success",
    "yes1": "emphatic yes / agreement",
    "no1": "emphatic no / disagreement",
    "shy1": "shy, bashful",
    "calming1": "reassuring, calming someone down",
    "tired1": "tired, sleepy",
    "dance1": "dancing when asked to dance",
}


def build_test_tools(emotion_names: Optional[list] = None) -> list:
    """Build the general tool set.

    Args:
        emotion_names: Names actually present in the loaded emotions library.
            ``play_emotion`` is only advertised if this is non-empty, so the
            model can never call a clip we cannot play.
    """
    available = [n for n in EMOTION_CHOICES if n in set(emotion_names or [])]

    emotion_tools = []
    if available:
        emotion_tools.append(
            genai_types.FunctionDeclaration(
                name="play_emotion",
                description=(
                    "Play a short pre-recorded emotional body-language clip "
                    "(head, body and antennas move together, with sound). "
                    "Use for a genuine emotional beat, a few times per "
                    "conversation at most -- not as punctuation on every "
                    "reply. Interrupts any clip already playing. Options: "
                    + "; ".join(f"{n} = {EMOTION_CHOICES[n]}" for n in available)
                ),
                parameters=genai_types.Schema(
                    type=genai_types.Type.OBJECT,
                    properties={
                        "name": genai_types.Schema(
                            type=genai_types.Type.STRING,
                            enum=available,
                            description="Which emotion clip to play.",
                        ),
                    },
                    required=["name"],
                ),
            )
        )

    return [
        genai_types.Tool(
            function_declarations=emotion_tools + [
                genai_types.FunctionDeclaration(
                    name="ping",
                    description="Health-check. Returns 'pong'.",
                    parameters=genai_types.Schema(type=genai_types.Type.OBJECT, properties={}),
                ),
                genai_types.FunctionDeclaration(
                    name="get_robot_status",
                    description="Return basic robot runtime status.",
                    parameters=genai_types.Schema(type=genai_types.Type.OBJECT, properties={}),
                ),
                genai_types.FunctionDeclaration(
                    name="set_head_angle",
                    description=(
                        "Move the robot's head to a specific yaw and pitch "
                        "angle in degrees. yaw=0 looks straight ahead; "
                        "positive yaw turns left, negative turns right. "
                        "pitch=0 is level; positive looks down, negative "
                        "looks up. Range: yaw -60..+60, pitch -30..+30."
                    ),
                    parameters=genai_types.Schema(
                        type=genai_types.Type.OBJECT,
                        properties={
                            "yaw_deg": genai_types.Schema(
                                type=genai_types.Type.NUMBER,
                                description="Head yaw in degrees. 0=center, +=left, -=right. Range -60..60.",
                            ),
                            "pitch_deg": genai_types.Schema(
                                type=genai_types.Type.NUMBER,
                                description="Head pitch in degrees. 0=level, +=down, -=up. Range -30..30.",
                            ),
                        },
                        required=["yaw_deg", "pitch_deg"],
                    ),
                ),
                genai_types.FunctionDeclaration(
                    name="look_straight",
                    description="Reset the robot's head to center (yaw=0, pitch=0).",
                    parameters=genai_types.Schema(type=genai_types.Type.OBJECT, properties={}),
                ),
                genai_types.FunctionDeclaration(
                    name="look_left",
                    description="Turn the robot's head 30 degrees to the left.",
                    parameters=genai_types.Schema(type=genai_types.Type.OBJECT, properties={}),
                ),
                genai_types.FunctionDeclaration(
                    name="look_right",
                    description="Turn the robot's head 30 degrees to the right.",
                    parameters=genai_types.Schema(type=genai_types.Type.OBJECT, properties={}),
                ),
                genai_types.FunctionDeclaration(
                    name="look_up",
                    description="Tilt the robot's head 15 degrees up.",
                    parameters=genai_types.Schema(type=genai_types.Type.OBJECT, properties={}),
                ),
                genai_types.FunctionDeclaration(
                    name="look_down",
                    description="Tilt the robot's head 15 degrees down.",
                    parameters=genai_types.Schema(type=genai_types.Type.OBJECT, properties={}),
                ),
                genai_types.FunctionDeclaration(
                    name="enable_face_follow",
                    description="Enable automatic face tracking.",
                    parameters=genai_types.Schema(type=genai_types.Type.OBJECT, properties={}),
                ),
                genai_types.FunctionDeclaration(
                    name="disable_face_follow",
                    description="Disable automatic face tracking.",
                    parameters=genai_types.Schema(type=genai_types.Type.OBJECT, properties={}),
                ),
                genai_types.FunctionDeclaration(
                    name="show_content",
                    description=(
                        "Show a company video on the presentation screen. "
                        "Searches the Tatweer group video catalog (videos "
                        "only -- no websites). Use for requests like "
                        "'play the Rafed yellow-bus video' or 'show the "
                        "TETCO future video'."
                    ),
                    parameters=genai_types.Schema(
                        type=genai_types.Type.OBJECT,
                        properties={
                            "query": genai_types.Schema(
                                type=genai_types.Type.STRING,
                                description=(
                                    "What video to show, e.g. 'فيديو "
                                    "حافلتي الصفراء' or 'فيديو تيتكو'."
                                ),
                            ),
                        },
                        required=["query"],
                    ),
                ),
                genai_types.FunctionDeclaration(
                    name="add_tile",
                    description=(
                        "Add ONE tile to the dashboard on the presentation "
                        "screen. Call it 3-4 times in a row to build a full "
                        "dashboard -- one tile alone looks empty. Every tile "
                        "type uses the same two parallel arrays: labels[] and "
                        "values[] (or text_values[] for a table). "
                        "Example, 'show me Rafed's numbers': "
                        "add_tile(title='أرقام رافد', type='kpi', "
                        "labels=['طلاب','حافلات','رحلات يومية'], "
                        "values=[740000,20000,40000]) then "
                        "add_tile(title='مقارنة عدد الطلاب', type='bar', "
                        "labels=['رافد','تطوير للمباني'], "
                        "values=[740000,764000], unit='طالب') then "
                        "add_tile(title='نمو الأسطول', type='line', "
                        "labels=['2022','2023','2024'], "
                        "values=[12000,16000,20000])."
                    ),
                    parameters=genai_types.Schema(
                        type=genai_types.Type.OBJECT,
                        properties={
                            "title": genai_types.Schema(
                                type=genai_types.Type.STRING,
                                description="Tile heading in Arabic, e.g. 'أرقام رافد'.",
                            ),
                            "type": genai_types.Schema(
                                type=genai_types.Type.STRING,
                                enum=list(TILE_TYPES),
                                description=(
                                    "kpi = big numbers (2-6 headline figures). "
                                    "bar = compare entities on one metric. "
                                    "pie = breakdown of a whole. "
                                    "line = trend over time (labels are years). "
                                    "table = non-numeric facts, needs text_values. "
                                    "map = pins on a map of Saudi Arabia, needs "
                                    "markers or latitude+longitude instead of "
                                    "labels/values."
                                ),
                            ),
                            "labels": genai_types.Schema(
                                type=genai_types.Type.ARRAY,
                                items=genai_types.Schema(type=genai_types.Type.STRING),
                                description="Name of each item, in Arabic. Not used by map.",
                            ),
                            "latitude": genai_types.Schema(
                                type=genai_types.Type.NUMBER,
                                description="map only: centre latitude, e.g. 24.7679888.",
                            ),
                            "longitude": genai_types.Schema(
                                type=genai_types.Type.NUMBER,
                                description="map only: centre longitude, e.g. 46.665489.",
                            ),
                            "zoom": genai_types.Schema(
                                type=genai_types.Type.NUMBER,
                                description="map only: 4 = whole Kingdom, 12 = city, 16 = building.",
                            ),
                            "markers": genai_types.Schema(
                                type=genai_types.Type.ARRAY,
                                items=genai_types.Schema(
                                    type=genai_types.Type.OBJECT,
                                    properties={
                                        "label": genai_types.Schema(
                                            type=genai_types.Type.STRING,
                                            description="Pin caption in Arabic.",
                                        ),
                                        "latitude": genai_types.Schema(type=genai_types.Type.NUMBER),
                                        "longitude": genai_types.Schema(type=genai_types.Type.NUMBER),
                                    },
                                    required=["label", "latitude", "longitude"],
                                ),
                                description="map only: pins to show, up to 8.",
                            ),
                            "values": genai_types.Schema(
                                type=genai_types.Type.ARRAY,
                                items=genai_types.Schema(type=genai_types.Type.NUMBER),
                                description=(
                                    "Plain numbers, one per label, same order. "
                                    "No separators or words: 740000, not '740 ألف'."
                                ),
                            ),
                            "text_values": genai_types.Schema(
                                type=genai_types.Type.ARRAY,
                                items=genai_types.Schema(type=genai_types.Type.STRING),
                                description=(
                                    "Only for type='table': short Arabic text per "
                                    "label instead of numbers."
                                ),
                            ),
                            "unit": genai_types.Schema(
                                type=genai_types.Type.STRING,
                                description=(
                                    "Optional unit shown after the numbers, e.g. "
                                    "'طالب', 'مدرسة', '%', 'ريال'."
                                ),
                            ),
                            "dashboard_title": genai_types.Schema(
                                type=genai_types.Type.STRING,
                                description=(
                                    "Overall heading, e.g. 'نظرة عامة على رافد'. "
                                    "Used only when the screen is idle or showing "
                                    "a video. It never removes existing tiles -- to "
                                    "replace the current dashboard with a new one, "
                                    "call clear_display first."
                                ),
                            ),
                        },
                        required=["title", "type"],
                    ),
                ),
                genai_types.FunctionDeclaration(
                    name="clear_display",
                    description="Clear the presentation screen -- removes all charts and videos, returns to idle.",
                    parameters=genai_types.Schema(type=genai_types.Type.OBJECT, properties={}),
                ),
            ],
        ),
    ]


def build_face_tools() -> list:
    return [
        genai_types.Tool(
            function_declarations=[
                genai_types.FunctionDeclaration(
                    name="enroll_face",
                    description=(
                        "Remember the face of a person visible to the "
                        "camera under the given name."
                    ),
                    parameters=genai_types.Schema(
                        type=genai_types.Type.OBJECT,
                        properties={
                            "name": genai_types.Schema(
                                type=genai_types.Type.STRING,
                                description="The person's name, e.g. 'Husam'.",
                            ),
                            "position": genai_types.Schema(
                                type=genai_types.Type.STRING,
                                description="Optional: 'left', 'center', 'right'.",
                            ),
                        },
                        required=["name"],
                    ),
                ),
                genai_types.FunctionDeclaration(
                    name="identify_person",
                    description=(
                        "Recognize EVERY person currently visible. Returns "
                        "names (or 'unknown') and positions."
                    ),
                    parameters=genai_types.Schema(type=genai_types.Type.OBJECT, properties={}),
                ),
                genai_types.FunctionDeclaration(
                    name="find_person",
                    description="Check whether a specific known person is visible.",
                    parameters=genai_types.Schema(
                        type=genai_types.Type.OBJECT,
                        properties={
                            "name": genai_types.Schema(
                                type=genai_types.Type.STRING,
                                description="The known person's name.",
                            ),
                        },
                        required=["name"],
                    ),
                ),
                genai_types.FunctionDeclaration(
                    name="list_known_people",
                    description="List the names of everyone enrolled in memory.",
                    parameters=genai_types.Schema(type=genai_types.Type.OBJECT, properties={}),
                ),
                genai_types.FunctionDeclaration(
                    name="who_is_speaking",
                    description=(
                        "Return the name of the person whose mouth is "
                        "currently moving (who is talking right now)."
                    ),
                    parameters=genai_types.Schema(type=genai_types.Type.OBJECT, properties={}),
                ),
                genai_types.FunctionDeclaration(
                    name="focus_on_person",
                    description="Lock the robot's head onto a named person.",
                    parameters=genai_types.Schema(
                        type=genai_types.Type.OBJECT,
                        properties={
                            "name": genai_types.Schema(
                                type=genai_types.Type.STRING,
                                description="Known person's name.",
                            ),
                        },
                        required=["name"],
                    ),
                ),
                genai_types.FunctionDeclaration(
                    name="focus_on_speaker",
                    description="Switch to speaker-tracking mode.",
                    parameters=genai_types.Schema(type=genai_types.Type.OBJECT, properties={}),
                ),
                genai_types.FunctionDeclaration(
                    name="clear_focus",
                    description="Return to default focus behavior (follow closest person).",
                    parameters=genai_types.Schema(type=genai_types.Type.OBJECT, properties={}),
                ),
                genai_types.FunctionDeclaration(
                    name="describe_scene",
                    description=(
                        "Return a compact summary of the current world "
                        "state: everyone visible, their direction, whether "
                        "they are speaking."
                    ),
                    parameters=genai_types.Schema(type=genai_types.Type.OBJECT, properties={}),
                ),
            ],
        ),
    ]


# --- Tool handler -----------------------------------------------------------

def make_tool_handler(
    mini: ReachyMini,
    detector: cv2.FaceDetectorYN,
    recognizer: cv2.FaceRecognizerSF,
    face_db: SimpleFaceDB,
    latest: LatestFrame,
    mouth_state: dict,
    emotion_player: Optional["EmotionPlayer"] = None,
):
    """Build the async tool handler for Gemini Live."""

    _SETTLE_S = 0.4
    _manual_mode = {"active": False}
    url_catalog = load_url_catalog()

    def _head_to(yaw_deg, pitch_deg):
        """Move head to angle and disable face follow."""
        _manual_mode["active"] = True
        try:
            mini.stop_head_tracking()
        except Exception:
            pass
        pose = create_head_pose(yaw=math.radians(yaw_deg),
                                pitch=math.radians(pitch_deg), degrees=False)
        try:
            mini.set_target(head=pose)
        except Exception as e:
            log.warning("set_target failed: %s", e)

    def _resume_face_follow():
        """Re-enable daemon face tracking."""
        _manual_mode["active"] = False
        try:
            mini.start_head_tracking(weight=TRACK_WEIGHT)
        except Exception as e:
            log.warning("start_head_tracking failed: %s", e)

    async def handler(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        # --- Head movement tools ---
        if name == "set_head_angle":
            yaw = max(-60, min(60, float(args.get("yaw_deg", 0))))
            pitch = max(-30, min(30, float(args.get("pitch_deg", 0))))
            _head_to(yaw, pitch)
            await asyncio.sleep(_SETTLE_S)
            return {"ok": True, "yaw_deg": yaw, "pitch_deg": pitch,
                    "next_action_hint": "Continue searching autonomously if needed."}

        if name == "look_straight":
            _head_to(0, 0); await asyncio.sleep(_SETTLE_S)
            return {"ok": True, "yaw_deg": 0, "pitch_deg": 0}

        if name == "look_left":
            _head_to(30, 0); await asyncio.sleep(_SETTLE_S)
            return {"ok": True, "yaw_deg": 30, "pitch_deg": 0}

        if name == "look_right":
            _head_to(-30, 0); await asyncio.sleep(_SETTLE_S)
            return {"ok": True, "yaw_deg": -30, "pitch_deg": 0}

        if name == "look_up":
            _head_to(0, -15); await asyncio.sleep(_SETTLE_S)
            return {"ok": True, "yaw_deg": 0, "pitch_deg": -15}

        if name == "look_down":
            _head_to(0, 15); await asyncio.sleep(_SETTLE_S)
            return {"ok": True, "yaw_deg": 0, "pitch_deg": 15}

        if name == "enable_face_follow":
            _resume_face_follow()
            return {"ok": True, "mode": "auto_follow"}

        if name == "disable_face_follow":
            _manual_mode["active"] = True
            try:
                mini.stop_head_tracking()
            except Exception:
                pass
            return {"ok": True, "mode": "manual"}

        # --- Presentation screen tools ---
        if name == "show_content":
            query = str(args.get("query", "")).strip()
            entry = find_url_entry(url_catalog, query)
            if not entry:
                return {"ok": False, "reason": "not_found",
                        "available_titles": [e.get("title") for e in url_catalog]}
            if entry.get("type") != "video":
                return {"ok": False, "reason": "not_video",
                        "note": "Only videos are supported. Use add_tile for company data."}
            state.set_video(entry.get("url", ""), entry.get("title", ""))
            return {"ok": True, "title": entry.get("title"),
                    "type": "video",
                    "note": "Now playing on the presentation screen."}

        if name == "add_tile":
            tile, note = normalize_tile(args)
            if tile is None:
                return {"ok": False, "error": note}

            # dashboard_title must NEVER destroy tiles. Gemini passes it
            # unreliably (sometimes mid-build), and a late title used to wipe
            # the whole dashboard. A dashboard begins only when the screen
            # isn't already showing one or is empty; replacing content
            # requires an explicit clear_display call.
            dash_title = str(args.get("dashboard_title", "")).strip()
            if state.display_mode != "dashboard" or not state.display_tiles:
                state.begin_dashboard(dash_title or tile["title"])

            count = state.add_tile(tile)
            result = {"ok": True, "title": tile["title"], "type": tile["type"],
                      "tiles_now": count}
            if note:
                result["adjusted"] = note
            # Nudging beats prompt rules: the model reliably keeps going until
            # the dashboard is full rather than stopping after one tile.
            if count < 3:
                result["note"] = (
                    f"{count} tile(s) so far -- add {3 - count} more with "
                    "another add_tile call, then speak."
                )
            else:
                result["note"] = "Dashboard looks complete. Speak now."
            return result

        if name == "clear_display":
            state.clear_display()
            return {"ok": True}

        # --- Face tools ---
        if name == "enroll_face":
            person = str(args.get("name", "")).strip().lower()
            if not person:
                return {"ok": False, "error": "name is required"}
            frame = latest.get_frame()
            if frame is None:
                return {"ok": False, "error": "no_frame"}
            resized, scale = resize_for_inference(frame, INFER_SIZE)
            rh, rw = resized.shape[:2]
            faces = detect_faces(detector, resized, input_size=(rw, rh))
            if faces is None or faces.shape[0] == 0:
                return {"ok": False, "reason": "no_face_visible"}

            # Pick face by position hint or largest
            position_hint = (args.get("position") or "").strip().lower() or None
            target_idx = 0
            if position_hint and faces.shape[0] > 1:
                centers = [(faces[i][0] + faces[i][2]/2) / rw for i in range(faces.shape[0])]
                if position_hint == "left":
                    target_idx = int(np.argmin(centers))
                elif position_hint == "right":
                    target_idx = int(np.argmax(centers))
                else:
                    target_idx = int(np.argmin([abs(c - 0.5) for c in centers]))
            else:
                areas = [faces[i][2] * faces[i][3] for i in range(faces.shape[0])]
                target_idx = int(np.argmax(areas))

            aligned = recognizer.alignCrop(resized, faces[target_idx])
            feat = recognizer.feature(aligned)
            face_db.add(person, feat)
            return {"ok": True, "name": person, "samples_captured": 1}

        if name == "identify_person":
            frame = latest.get_frame()
            if frame is None:
                return {"ok": False, "reason": "no_frame"}
            resized, scale = resize_for_inference(frame, INFER_SIZE)
            rh, rw = resized.shape[:2]
            faces = detect_faces(detector, resized, input_size=(rw, rh))
            if faces is None or faces.shape[0] == 0:
                return {"ok": False, "reason": "no_face_visible"}
            people = []
            for i in range(faces.shape[0]):
                aligned = recognizer.alignCrop(resized, faces[i])
                feat = recognizer.feature(aligned)
                identified = face_db.identify(feat, recognizer)
                cx = (faces[i][0] + faces[i][2]/2) / rw
                pos = "left" if cx < 0.33 else ("right" if cx > 0.66 else "center")
                people.append({"name": identified or "unknown", "position": pos})
            return {"ok": True, "count": len(people), "people": people}

        if name == "find_person":
            target = str(args.get("name", "")).strip().lower()
            if not target:
                return {"ok": False, "error": "name is required"}
            frame = latest.get_frame()
            if frame is None:
                return {"ok": True, "found": False, "name": target}
            resized, scale = resize_for_inference(frame, INFER_SIZE)
            rh, rw = resized.shape[:2]
            faces = detect_faces(detector, resized, input_size=(rw, rh))
            if faces is None or faces.shape[0] == 0:
                return {"ok": True, "found": False, "name": target}
            for i in range(faces.shape[0]):
                aligned = recognizer.alignCrop(resized, faces[i])
                feat = recognizer.feature(aligned)
                identified = face_db.identify(feat, recognizer)
                if identified == target:
                    cx = (faces[i][0] + faces[i][2]/2) / rw
                    pos = "left" if cx < 0.33 else ("right" if cx > 0.66 else "center")
                    return {"ok": True, "found": True, "name": target, "position": pos}
            return {"ok": True, "found": False, "name": target}

        if name == "list_known_people":
            return {"ok": True, "names": face_db.list_names()}

        if name == "who_is_speaking":
            energies = mouth_state.get("energies", [])
            labels = mouth_state.get("labels", [])
            speaker_idx = mouth_state.get("speaker_id", -1)
            if speaker_idx < 0 or speaker_idx >= len(labels):
                return {"ok": True, "is_anyone_speaking": False, "speaker": None}
            return {"ok": True, "is_anyone_speaking": True,
                    "speaker": labels[speaker_idx]}

        if name == "focus_on_person":
            # On Pi, we just re-enable face follow (daemon tracks closest)
            _resume_face_follow()
            return {"ok": True, "mode": "auto_follow",
                    "note": "Daemon tracks closest face. Person-specific lock not available on Pi."}

        if name == "focus_on_speaker":
            _resume_face_follow()
            return {"ok": True, "mode": "auto_follow"}

        if name == "clear_focus":
            _resume_face_follow()
            return {"ok": True, "mode": "auto"}

        if name == "describe_scene":
            frame = latest.get_frame()
            if frame is None:
                return {"ok": False, "error": "no_frame"}
            resized, scale = resize_for_inference(frame, INFER_SIZE)
            rh, rw = resized.shape[:2]
            faces = detect_faces(detector, resized, input_size=(rw, rh))
            n = faces.shape[0] if faces is not None else 0
            people = []
            for i in range(n):
                cx = (faces[i][0] + faces[i][2]/2) / rw
                pos = "left" if cx < 0.33 else ("right" if cx > 0.66 else "center")
                people.append({"position": pos, "speaking": i == mouth_state.get("speaker_id", -1)})
            return {"ok": True, "people_count": n, "people": people,
                    "robot_speaking": state.gemini_speaking,
                    "tracking": state.tracking_active}

        # --- Utility tools ---
        if name == "ping":
            return {"ok": True, "pong": True}

        if name == "get_robot_status":
            return {"ok": True, "face_recognition": True,
                    "head_tracking": state.tracking_active,
                    "gemini_connected": state.gemini_connected}

        # --- Body language ---
        if name == "play_emotion":
            if emotion_player is None:
                return {"ok": False, "error": "emotions library not loaded"}
            emotion = str(args.get("name", "")).strip()
            if not emotion:
                return {"ok": False, "error": "name is required"}

            # Fire-and-forget: the clip runs for a second or more and the
            # model should keep talking over it, not block on it. Only hand
            # the head back to tracking if it was tracking to begin with.
            resume = not _manual_mode["active"]

            async def _emotion_task():
                try:
                    await emotion_player.play(
                        emotion, TRACK_WEIGHT, resume_tracking=resume,
                    )
                except Exception:
                    log.exception("play_emotion task failed")

            asyncio.create_task(_emotion_task())
            return {"ok": True, "emotion": emotion, "status": "playing"}

        return {"ok": False, "error": f"unknown tool: {name}"}

    return handler


# --- Vision loop ------------------------------------------------------------

def draw_overlay(frame, faces, scale, speaker_id, labels, energies):
    """Draw detection boxes + HUD on the frame."""
    h = frame.shape[0]
    n = faces.shape[0] if faces is not None else 0

    for i in range(n):
        f = faces[i]
        x = int(f[0] * scale); y = int(f[1] * scale)
        bw = int(f[2] * scale); bh = int(f[3] * scale)
        is_speaker = (i == speaker_id)
        color = (0, 255, 0) if is_speaker else (0, 200, 255)
        cv2.rectangle(frame, (x, y), (x + bw, y + bh), color, 2)
        for j in range(5):
            lx = int(f[4 + j * 2] * scale); ly = int(f[5 + j * 2] * scale)
            cv2.circle(frame, (lx, ly), 3, color, -1)
        label = labels[i] if i < len(labels) else f"face{i}"
        if is_speaker:
            label += " [SPEAKING]"
        cv2.putText(frame, label, (x, y - 8), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, color, 1, cv2.LINE_AA)

    # HUD
    track_status = "ON" if state.tracking_active else "OFF"
    gemini_status = "TALKING" if state.gemini_speaking else ("ON" if state.gemini_connected else "OFF")
    info = (f"FPS:{state.fps:.0f} Faces:{state.n_faces} Track:{track_status} "
            f"Voice:{gemini_status}")
    cv2.putText(frame, info, (10, 25), cv2.FONT_HERSHEY_SIMPLEX,
                0.5, (0, 255, 0), 2, cv2.LINE_AA)

    cv2.putText(frame, "Ctrl-C to quit", (10, h - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (150, 150, 150), 1, cv2.LINE_AA)


def vision_loop(mini, detector, recognizer, face_db, latest, mouth_state):
    """Main loop: capture -> detect -> annotate -> serve."""
    mouth_bufs: dict[int, deque] = {}
    frame_count = 0
    fps_counter = 0
    fps_time = time.time()
    fps = 0.0

    print("[vision] Starting visualization loop...")
    print("[vision] Head tracking: daemon (start_head_tracking)")
    print("[vision] Face ID: SFace (every %d frames)" % SFACE_INTERVAL)

    while state.running:
        t_start = time.perf_counter()

        # --- Capture from daemon camera ---
        # NOTE: the daemon's GStreamer pipeline negotiates caps
        # video/x-raw,format=BGR (camera_gstreamer.py), so frames are
        # already BGR -- do NOT run RGB2BGR here (it swaps red/blue).
        frame = mini.media.get_frame()
        if frame is None:
            time.sleep(0.01)
            continue

        h, w = frame.shape[:2]
        frame_count += 1
        latest.set(frame)

        # --- YuNet detection ---
        resized, scale = resize_for_inference(frame, INFER_SIZE)
        rh, rw = resized.shape[:2]
        faces = detect_faces(detector, resized, input_size=(rw, rh))
        n_faces = faces.shape[0] if faces is not None else 0

        # --- Per-face: mouth energy + occasional SFace ID ---
        labels = []
        energies = []
        speaker_id = -1
        best_energy = MOUTH_ENERGY_FLOOR

        if faces is not None and n_faces > 0:
            for i in range(n_faces):
                # Mouth energy (cheap: 1.5ms)
                aligned = recognizer.alignCrop(resized, faces[i])
                mouth = cv2.cvtColor(aligned[74:112, 28:84], cv2.COLOR_BGR2GRAY)
                mouth = cv2.GaussianBlur(mouth, (5, 5), 0).astype(np.float32) / 255.0
                mouth_bufs.setdefault(i, deque(maxlen=MOUTH_BUF_LEN))
                mouth_bufs[i].append(mouth)
                if len(mouth_bufs[i]) > 5:
                    energy = float(np.mean(np.var(np.stack(mouth_bufs[i]), axis=0)))
                else:
                    energy = 0.0
                energies.append(energy)
                if energy > best_energy:
                    best_energy = energy
                    speaker_id = i

                # SFace ID (expensive: only every SFACE_INTERVAL frames)
                if frame_count % SFACE_INTERVAL == 0:
                    feat = recognizer.feature(aligned)
                    identified = face_db.identify(feat, recognizer)
                    labels.append(identified or f"face{i}")
                else:
                    labels.append(f"face{i}")

        # Update mouth state for tool handler
        mouth_state["energies"] = energies
        mouth_state["labels"] = labels
        mouth_state["speaker_id"] = speaker_id

        # --- Annotate + encode ---
        annotated = frame.copy()
        draw_overlay(annotated, faces, scale, speaker_id, labels, energies)
        ok, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if ok:
            state.set_frame(buf.tobytes(), fps=fps, n_faces=n_faces,
                            speaker_id=speaker_id, face_labels=labels,
                            tracking_active=not _manual_mode_active(mini))

        # --- FPS ---
        fps_counter += 1
        elapsed = time.time() - fps_time
        if elapsed >= 1.0:
            fps = fps_counter / elapsed
            fps_counter = 0
            fps_time = time.time()
            print(f"[vision] {fps:.1f} FPS | {n_faces} faces | "
                  f"speaker={'face'+str(speaker_id) if speaker_id>=0 else '-'}")

        # --- Pace ---
        dt = time.perf_counter() - t_start
        if dt < 0.033:
            time.sleep(0.033 - dt)


_manual_flag = {"active": False}

def _manual_mode_active(mini):
    return _manual_flag["active"]


# --- Main -------------------------------------------------------------------

def main() -> None:
    global TRACK_WEIGHT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-gemini", action="store_true",
                        help="Run tracking only (no voice)")
    parser.add_argument("--voice", default="Puck",
                        help="Gemini prebuilt voice name (default: Puck)")
    parser.add_argument("--model", default=None,
                        help="Gemini Live model name")
    parser.add_argument("--video-fps", type=float, default=1.0,
                        help="Camera frames per second to stream to Gemini")
    parser.add_argument("--no-face-recognition", action="store_true",
                        help="Disable face enrollment/identification")
    parser.add_argument("--track-weight", type=float, default=TRACK_WEIGHT,
                        help="Daemon head tracking weight (0-1)")
    parser.add_argument("--no-wobble", action="store_true",
                        help="Disable audio-reactive head wobbling")
    parser.add_argument("--no-emotions", action="store_true",
                        help="Disable the play_emotion tool (emotions library)")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    TRACK_WEIGHT = args.track_weight

    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

    print("=" * 60)
    print("Hsafa Robot - Reachy Mini (Pi lightweight build)")
    print("=" * 60)

    # --- Load models ---
    print("Loading models...")
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    download(YUNET_URL, YUNET_PATH)
    download(SFACE_URL, SFACE_PATH)
    detector = cv2.FaceDetectorYN.create(
        str(YUNET_PATH), "", (INFER_SIZE, INFER_SIZE),
        score_threshold=CONF_THRESHOLD, nms_threshold=NMS_THRESHOLD, top_k=TOP_K,
    )
    recognizer = cv2.FaceRecognizerSF.create(str(SFACE_PATH), "")
    print("  YuNet + SFace loaded")

    # --- Face DB ---
    face_db = SimpleFaceDB(FACE_DB_DIR)
    if face_db.list_names():
        print(f"  Known people: {face_db.list_names()}")

    # --- Connect to robot ---
    print("Connecting to robot...")
    mini = ReachyMini(media_backend="default")
    print("  connected")

    # --- Wake up ---
    print("Enabling motors + waking up...")
    mini.enable_motors()
    mini.wake_up()
    time.sleep(1.0)
    print("  awake!")

    # --- Start daemon head tracking ---
    print("Starting daemon head tracking (weight=%.1f)..." % TRACK_WEIGHT)
    try:
        mini.start_head_tracking(weight=TRACK_WEIGHT)
        print("  head tracking ON")
    except Exception as exc:
        print(f"  WARNING: start_head_tracking failed: {exc}")

    # --- Audio ---
    media = mini.media
    gemini_audio_ok = media is not None and getattr(media, "audio", None) is not None
    if gemini_audio_ok:
        media.start_recording()
        media.start_playing()
        print(f"  Audio ready: in={media.get_input_audio_samplerate()}Hz "
              f"out={media.get_output_audio_samplerate()}Hz")
        set_full_volume()
    elif not args.no_gemini:
        print("  WARNING: No audio - Gemini voice disabled")
        args.no_gemini = True

    # --- Audio-reactive head wobble (SDK) ---
    # Analyses everything pushed to the speaker and composes 6-DOF head
    # offsets daemon-side *before* IK, so it layers on top of head tracking
    # instead of fighting it. This replaces any hand-rolled talking animation.
    if gemini_audio_ok and not args.no_wobble:
        try:
            mini.enable_wobbling()
            print("  head wobbling ON (audio-reactive)")
        except Exception as exc:
            print(f"  WARNING: enable_wobbling failed: {exc}")

    # --- Emotions library (SDK recorded moves) ---
    emotion_player: Optional[EmotionPlayer] = None
    if not args.no_emotions:
        emotion_player = EmotionPlayer(mini)
        if emotion_player.load():
            print(f"  emotions library loaded ({len(emotion_player.names)} clips)")
        else:
            print("  WARNING: emotions library unavailable - play_emotion disabled")
            emotion_player = None

    # --- Shared state ---
    latest = LatestFrame()
    mouth_state: dict = {"energies": [], "labels": [], "speaker_id": -1}
    gemini: Optional[GeminiLiveSession] = None

    # --- Mic source tee ---
    def _mic_source_tee():
        sample = media.get_audio_sample()
        return sample

    # --- Gemini Live ---
    if not args.no_gemini:
        if not api_key:
            print("  WARNING: GEMINI_API_KEY not set - running without voice")
        else:
            print("Starting Gemini Live...")
            kwargs = dict(
                api_key=api_key,
                voice_name=args.voice,
                system_instruction=build_system_instruction(),
                frame_source=latest.get_jpeg,
                video_fps=args.video_fps,
                mic_source=_mic_source_tee,
                speaker_sink=media.push_audio_sample,
            )
            all_tools = []
            if not args.no_face_recognition:
                all_tools.extend(build_face_tools())
            all_tools.extend(build_test_tools(
                emotion_names=emotion_player.names if emotion_player else None,
            ))
            if all_tools:
                kwargs["tools"] = all_tools
                kwargs["tool_handler"] = make_tool_handler(
                    mini, detector, recognizer, face_db, latest,
                    mouth_state, emotion_player,
                )
            model = args.model or os.environ.get("GEMINI_MODEL")
            if model:
                kwargs["model"] = model
            try:
                gemini = GeminiLiveSession(**kwargs)
                gemini.start()
                state.gemini_connected = True
                print("  Gemini Live started")
            except Exception as exc:
                print(f"  WARNING: Gemini Live failed: {exc}")
                gemini = None

    # --- Presentation panel ---
    global PANEL_URL, PANEL_TOKEN
    PANEL_URL = os.environ.get("PANEL_URL", "")
    PANEL_TOKEN = os.environ.get("HSAFA_PANEL_TOKEN", "")
    panel = None
    if PANEL_URL:
        panel = PanelClient(
            PANEL_URL, PANEL_TOKEN, snapshot=state.snapshot_events
        )
        state.attach_panel(panel)
        panel.start()
        print(f"  Panel: {PANEL_URL}")
    else:
        print(f"  Panel: not configured (local screen only, :{HTTP_PORT}/display)")

    # --- HTTP server ---
    http_thread = threading.Thread(target=start_http_server, daemon=True)
    http_thread.start()

    print()
    print(f">>> Open: http://reachy-mini.local:{HTTP_PORT}/")
    print(">>> Press Ctrl-C to quit.")
    print()

    # --- Signal handling ---
    stop = {"flag": False}
    def _sigint(_sig, _frm):
        stop["flag"] = True
    signal.signal(signal.SIGINT, _sigint)

    # --- Antenna idle breathe ---
    breather = AntennaBreather()

    # --- Main loop ---
    try:
        while not stop["flag"]:
            if gemini is not None:
                state.set_speaking(gemini.is_speaking.is_set())
            try:
                vision_loop_step(mini, detector, recognizer, face_db, latest, mouth_state)

                # Antenna breathe. Muted while an emotion clip is playing --
                # recorded moves drive the antennas themselves, and two
                # writers would fight over them.
                playing = (
                    emotion_player is not None
                    and emotion_player.is_playing.is_set()
                )
                if not playing:
                    r_ant, l_ant = breather.tick()
                    try:
                        mini.set_target(antennas=[r_ant, l_ant])
                    except Exception:
                        pass
            except Exception as e:
                if not stop["flag"]:
                    log.debug("vision_loop_step error: %s", e)
                time.sleep(0.05)
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        state.running = False
        time.sleep(0.3)

        print("Stopping head tracking...")
        try:
            mini.stop_head_tracking()
        except Exception:
            pass

        # Cancel any in-flight emotion clip and zero the wobbler offsets --
        # leftover offsets would be composed into the goto_sleep pose.
        if emotion_player is not None and emotion_player.is_playing.is_set():
            try:
                mini.cancel_move()
            except Exception:
                pass
        try:
            mini.disable_wobbling()
        except Exception:
            pass

        if gemini is not None:
            print("Stopping Gemini...")
            gemini.stop()

        if panel is not None:
            panel.stop()

        print("Going to sleep...")
        try:
            mini.goto_sleep()
            time.sleep(1.0)
        except Exception:
            pass

        try:
            mini.__exit__(None, None, None)
        except Exception:
            pass
        print("Done.")


def vision_loop_step(mini, detector, recognizer, face_db, latest, mouth_state):
    """Single iteration of the vision loop (extracted for clarity)."""
    t_start = time.perf_counter()

    # Frames arrive in BGR from the daemon (see vision_loop note).
    frame = mini.media.get_frame()
    if frame is None:
        time.sleep(0.01)
        return

    h, w = frame.shape[:2]
    latest.set(frame)

    resized, scale = resize_for_inference(frame, INFER_SIZE)
    rh, rw = resized.shape[:2]
    faces = detect_faces(detector, resized, input_size=(rw, rh))
    n_faces = faces.shape[0] if faces is not None else 0

    labels = []
    energies = []
    speaker_id = -1
    best_energy = MOUTH_ENERGY_FLOOR

    if faces is not None and n_faces > 0:
        for i in range(n_faces):
            aligned = recognizer.alignCrop(resized, faces[i])
            mouth = cv2.cvtColor(aligned[74:112, 28:84], cv2.COLOR_BGR2GRAY)
            mouth = cv2.GaussianBlur(mouth, (5, 5), 0).astype(np.float32) / 255.0
            buf = mouth_state.setdefault(f"buf_{i}", deque(maxlen=MOUTH_BUF_LEN))
            buf.append(mouth)
            if len(buf) > 5:
                energy = float(np.mean(np.var(np.stack(buf), axis=0)))
            else:
                energy = 0.0
            energies.append(energy)
            if energy > best_energy:
                best_energy = energy
                speaker_id = i

            if not hasattr(mouth_state, "_frame_count"):
                mouth_state["_frame_count"] = 0
            mouth_state["_frame_count"] = mouth_state.get("_frame_count", 0) + 1
            if mouth_state["_frame_count"] % SFACE_INTERVAL == 0:
                feat = recognizer.feature(aligned)
                identified = face_db.identify(feat, recognizer)
                labels.append(identified or f"face{i}")
            else:
                labels.append(f"face{i}")

    mouth_state["energies"] = energies
    mouth_state["labels"] = labels
    mouth_state["speaker_id"] = speaker_id

    annotated = frame.copy()
    draw_overlay(annotated, faces, scale, speaker_id, labels, energies)
    ok, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 75])
    if ok:
        state.set_frame(buf.tobytes(), fps=state.fps, n_faces=n_faces,
                        speaker_id=speaker_id, face_labels=labels,
                        tracking_active=True)

    dt = time.perf_counter() - t_start
    if dt < 0.033:
        time.sleep(0.033 - dt)


if __name__ == "__main__":
    main()
