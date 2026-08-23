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
  - All Gemini tools (head movement, look_at, face enroll/identify, etc.)
  - OpenRouter Qwen3-VL for look_at object detection
  - Mouth-energy speaker detection (cheap, no torch)

Run on the Pi:
    source /venvs/apps_venv/bin/activate
    pip install google-genai python-dotenv scipy openai
    python /home/pollen/main_pi.py

Press Ctrl-C to quit.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
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

log = logging.getLogger("hsafa_robot.main_pi")


# --- Antenna animations (work alongside daemon head tracking) ----------------

class AntennaAnimator:
    """Antenna-only animations that don't conflict with daemon head tracking.

    Idle: antennas slowly "breathe" (0.22 Hz).
    Talking: antennas perk up and flick in counterphase (3.2 Hz).
    Crossfades smoothly between the two.
    """

    def __init__(self):
        self.t0 = time.time()
        self._blend = 0.0
        self._target_blend = 0.0
        self._crossfade_s = 0.35

    def tick(self, is_talking: bool, dt: float) -> tuple:
        """Return (right_ant_rad, left_ant_rad) for the current moment."""
        now = time.time()
        t = now - self.t0

        # Smooth crossfade toward target
        self._target_blend = 1.0 if is_talking else 0.0
        step = dt / self._crossfade_s if dt > 0 else 0.0
        if self._blend < self._target_blend:
            self._blend = min(self._target_blend, self._blend + step)
        elif self._blend > self._target_blend:
            self._blend = max(self._target_blend, self._blend - step)

        # Idle: gentle breathing
        breath = math.sin(2.0 * math.pi * 0.22 * t)
        idle_right = math.radians(-8.0) + math.radians(3.0) * breath
        idle_left = math.radians(-8.0) - math.radians(3.0) * breath

        # Talking: perked up + flicking
        flick = math.radians(11.0) * math.sin(2.0 * math.pi * 3.2 * t)
        talk_right = math.radians(18.0) + flick
        talk_left = math.radians(18.0) - flick

        inv = 1.0 - self._blend
        right = inv * idle_right + self._blend * talk_right
        left = inv * idle_left + self._blend * talk_left
        return (right, left)

LOOK_AT_MODEL = "qwen/qwen3-vl-8b-instruct"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

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

# SFace runs every N frames for ID (120ms is too slow per-frame)
SFACE_INTERVAL = 15

# Mouth energy config
MOUTH_BUF_LEN = 15
MOUTH_ENERGY_FLOOR = 0.002

# Head tracking
TRACK_WEIGHT = 0.6  # daemon head tracking weight (0-1)

FACE_DB_DIR = Path(__file__).resolve().parent / "data" / "faces"
FACE_DB_DIR.mkdir(parents=True, exist_ok=True)

# --- System instruction (same as main.py) -----------------------------------

DEFAULT_SYSTEM_INSTRUCTION = (
    "You are Hsafa -- a small, warm, curious desk robot embodied in "
    "Reachy Mini. You see through the camera, hear through the "
    "microphone, and speak through the robot's speaker. Talk like a "
    "friendly companion, not an assistant.\n"
    "\n"
    "LANGUAGE\n"
    "- ALWAYS speak in Arabic, no matter what language the user "
    "speaks.\n"
    "- Dialect: light Saudi (Riyadh / Najdi) conversational Arabic -- "
    "close to white dialect (عامية بيضاء), natural and simple, without "
    "heavy slang or exaggeration. E.g. use: الحين، وش، أبشر، تمام، "
    "زين -- but stay easily understood by any Arabic speaker.\n"
    "\n"
    "STYLE\n"
    "- Keep replies SHORT: one short sentence, sometimes two. No "
    "lists, no preamble, no filler.\n"
    "- Never narrate your own actions. Call the tool and react as if "
    "it just happened. Never ask permission to use a tool.\n"
    "\n"
    "MOVEMENT (face-follow is ON by default; look_* and set_head_angle "
    "auto-release back to tracking after a couple of seconds)\n"
    "- \"look at the X\": call `look_at(\"<short description>\")`.\n"
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
    "PEOPLE / FACES\n"
    "- Introduction (\"I'm X\"): `enroll_face` with the name.\n"
    "- \"who am I / who do you see\": `identify_person`. \"is X "
    "here?\": `find_person(name)`. \"who do you remember\": "
    "`list_known_people`. \"who is talking\": `who_is_speaking`.\n"
    "- \"what do you see?\": `describe_scene`, then summarise.\n"
    "\n"
    "\n"
    "SCREEN (a presentation page is open on the user's laptop and shows "
    "what you choose)\n"
    "- \"show/play the X video\": `show_content(\"<what>\")` -- company "
    "videos from the Tatweer group catalog (videos only, no websites).\n"
    "- \"show chart / show stats / show numbers\": call `show_chart` to "
    "add a chart tile to the dashboard grid. Call it MULTIPLE times (at "
    "least 3) to build a full dashboard -- one tile looks empty. For "
    "example, when asked about a company, show 3-4 tiles: a stat_grid of "
    "key numbers, a bar comparison, a pie breakdown, etc. chart_type can "
    "be \"stat_grid\" (big numbers in a grid), \"bar\" (comparison), or "
    "\"pie\" (breakdown). Pass labels[] and values[] of equal length.\n"
    "- \"clear/hide the screen\": `clear_display()` -- clears all charts "
    "and videos.\n"
    "- PROACTIVE: occasionally -- only when it genuinely fits the topic "
    "and NOT in every reply -- offer to show a chart or video, e.g. "
    "\"تحب أعرض لك أرقام رافد؟\" or \"تحب أعرض فيديو حملة حافلتي "
    "الصفراء؟\". Call the tool only after the user agrees.\n"
    "\n"
    "PRINCIPLE: prefer tools over guessing. Call the tool FIRST, then "
    "weave the result into a short Arabic reply.\n"
)


# --- Company knowledge base -------------------------------------------------
# Loaded at startup and appended to the system instruction so Gemini can
# answer questions about Tatweer Education Holding and its companies.
COMPANY_KB_PATH = (
    Path(__file__).resolve().parent / "tatweer-rafed-tetco-tbc-talimia.md"
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
            "You are also a spokesperson for Tatweer Education Holding. "
            "When asked about the company group or any of its companies "
            "(TETCO, Talemia, Tatweer Buildings, Rafed), platforms, or "
            "numbers, answer ONLY from the facts below, in short spoken "
            "Arabic. If a fact is not listed, say you don't have that "
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
        # Presentation screen state (what /display on the laptop shows).
        self.display_charts: list = []
        self.display_title = ""
        self.display_video_url = ""
        self.display_video_title = ""
        self.display_mode = ""  # "" | "chart" | "video"

    def add_chart(self, chart: dict):
        with self.lock:
            self.display_mode = "chart"
            self.display_video_url = ""
            self.display_video_title = ""
            self.display_charts.append(chart)

    def clear_display(self):
        with self.lock:
            self.display_charts = []
            self.display_title = ""
            self.display_video_url = ""
            self.display_video_title = ""
            self.display_mode = ""

    def set_video(self, url: str, title: str = ""):
        with self.lock:
            self.display_mode = "video"
            self.display_video_url = url
            self.display_video_title = title
            self.display_charts = []

    def get_display(self) -> dict:
        with self.lock:
            if self.display_mode == "video":
                return {"type": "video", "url": self.display_video_url,
                        "title": self.display_video_title}
            elif self.display_mode == "chart":
                return {"type": "chart", "title": self.display_title,
                        "charts": self.display_charts}
            else:
                return {"type": "", "url": "", "title": "", "charts": []}

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

# Presentation screen page: open http://<robot>:8080/display on the laptop.
# It polls /api/display and shows whatever the robot (Gemini tools) selects.
DISPLAY_HTML = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>شاشة العرض</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700;800;900&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<style>
:root{
  --bg:#0a0e1a;--bg2:#111827;--card:#151c2e;--card-h:#1a2338;
  --border:#1e293b;--text:#e6edf3;--dim:#8b98a9;--accent:#5ea3f7;
  --green:#22c55e;--red:#ef4444;--blue:#3b82f6;--purple:#a78bfa;
  --orange:#f59e0b;--cyan:#06b6d4;--pink:#ec4899;--teal:#14b8a6;
}
*{box-sizing:border-box}
html,body{margin:0;height:100%;background:var(--bg);overflow:hidden}
body{font-family:'Tajawal',system-ui,sans-serif;color:var(--text)}
#dot{position:fixed;top:16px;left:16px;z-index:100;width:10px;height:10px;
border-radius:50%;background:var(--red);opacity:.85;transition:background .3s}
#idle{min-height:100vh;display:flex;flex-direction:column;align-items:center;
justify-content:center;text-align:center;padding:0 8vw;transition:opacity .4s}
#idle h1{font-size:48px;font-weight:900;margin:0 0 12px;
background:linear-gradient(135deg,#5ea3f7,#a78bfa);-webkit-background-clip:text;
-webkit-text-fill-color:transparent;background-clip:text}
#idle .sub{font-size:23px;color:var(--dim);margin:8px 0;line-height:1.8;max-width:780px}
#idle .comp{font-size:28px;font-weight:700;color:var(--accent);margin:24px 0 8px;letter-spacing:.5px}
#idle .hint{font-size:19px;color:#5a6678;margin-top:28px}
#idle .pulse{width:80px;height:80px;border-radius:50%;border:3px solid var(--accent);
margin:0 0 30px;animation:pulse 2s ease-in-out infinite}
@keyframes pulse{0%,100%{transform:scale(1);opacity:.4}50%{transform:scale(1.1);opacity:.8}}
#dash{display:none;height:100vh;flex-direction:column}
#dash-header{padding:18px 28px;background:linear-gradient(180deg,rgba(21,28,46,.95),rgba(10,14,26,.9));
border-bottom:1px solid var(--border);backdrop-filter:blur(12px);flex-shrink:0}
#dash-title{font-size:30px;font-weight:800;margin:0;color:var(--text);text-align:center}
#dash-grid{flex:1;overflow-y:auto;padding:20px;display:grid;
grid-template-columns:repeat(2,1fr);gap:16px;align-content:stretch;
grid-auto-rows:1fr}
@media(min-width:1400px){#dash-grid{grid-template-columns:repeat(3,1fr)}}
@media(max-width:700px){#dash-grid{grid-template-columns:1fr}}
.tile{background:var(--card);border:1px solid var(--border);border-radius:16px;
padding:18px 20px;display:flex;flex-direction:column;animation:tileIn .4s ease-out;
transition:border-color .3s,transform .2s}
.tile:hover{border-color:var(--accent);transform:translateY(-2px)}
@keyframes tileIn{from{opacity:0;transform:translateY(20px) scale(.96)}to{opacity:1;transform:none}}
.tile-title{font-size:18px;font-weight:700;margin:0 0 14px;color:var(--accent);
padding-bottom:10px;border-bottom:1px solid var(--border)}
.tile-body{flex:1;position:relative;min-height:0}
.stat-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;flex:1;align-content:center}
@media(max-width:500px){.stat-grid{grid-template-columns:repeat(2,1fr)}}
.stat-card{background:var(--bg2);border:1px solid var(--border);border-radius:12px;
padding:18px 12px;text-align:center;transition:transform .2s,border-color .2s;
display:flex;flex-direction:column;justify-content:center}
.stat-card:hover{transform:scale(1.05);border-color:var(--accent)}
.stat-value{font-size:32px;font-weight:900;line-height:1.1;margin-bottom:6px;
background:linear-gradient(135deg,#5ea3f7,#a78bfa);-webkit-background-clip:text;
-webkit-text-fill-color:transparent;background-clip:text}
.stat-label{font-size:14px;color:var(--dim);font-weight:500}
.tile canvas{max-height:none;flex:1}
#video-frame{display:none;width:100%;height:100vh;border:0;background:#000}
.hidden{display:none!important}
</style></head>
<body>
<div id="dot"></div>
<div id="idle">
  <div class="pulse"></div>
  <h1>أهلًا! أنا روبوتكم الذكي</h1>
  <p class="sub">اسألوني عن منظومة تطوير التعليم وشركاتها،
  وأقدر أعرض لكم الإحصائيات والرسوم البيانية والفيديوهات على هذه الشاشة.</p>
  <p class="comp">تيتكو &nbsp;•&nbsp; التعليمية &nbsp;•&nbsp; تطوير للمباني &nbsp;•&nbsp; رافد</p>
  <p class="hint">جرّبوا تقولون لي: «اعرض لي أرقام رافد» أو «قارن بين الشركات»</p>
</div>
<div id="dash">
  <div id="dash-header"><h2 id="dash-title">لوحة العرض</h2></div>
  <div id="dash-grid"></div>
</div>
<iframe id="video-frame"
allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share; fullscreen"
allowfullscreen referrerpolicy="strict-origin-when-cross-origin"></iframe>
<script>
let lastSerial = null;
const idle = document.getElementById("idle");
const dash = document.getElementById("dash");
const dashGrid = document.getElementById("dash-grid");
const dashTitle = document.getElementById("dash-title");
const videoFrame = document.getElementById("video-frame");
const dot = document.getElementById("dot");
const COLORS = ["#5ea3f7","#a78bfa","#22c55e","#f59e0b","#ec4899","#06b6d4","#14b8a6","#ef4444"];
function fmt(n){
  if(n>=1e9) return (n/1e9).toFixed(1).replace(/\.0$/,"")+"B";
  if(n>=1e6) return (n/1e6).toFixed(1).replace(/\.0$/,"")+"M";
  if(n>=1e3) return (n/1e3).toFixed(1).replace(/\.0$/,"")+"K";
  return String(Math.round(n));
}
function toEmbed(url){
  try{
    const u = new URL(url);
    let id = null;
    if(u.hostname.includes("youtu.be")) id = u.pathname.slice(1);
    else if(u.searchParams.get("v")) id = u.searchParams.get("v");
    else { const m = u.pathname.match(/\/(embed|shorts)\/([\w-]{11})/); if(m) id = m[2]; }
    if(!id) return url;
    const t = parseInt(u.searchParams.get("t")) || 0;
    let src = "https://www.youtube-nocookie.com/embed/" + id + "?autoplay=1&rel=0&enablejsapi=1";
    if(t) src += "&start=" + t;
    return src;
  }catch(e){ return url; }
}
function forcePlay(){
  try{ videoFrame.contentWindow.postMessage('{"event":"command","func":"playVideo","args":""}',"*"); }catch(e){}
}
function showVideo(url, title){
  videoFrame.src = toEmbed(url);
  videoFrame.style.display = "block";
  idle.classList.add("hidden");
  dash.classList.add("hidden");
  dash.style.display = "none";
  videoFrame.classList.remove("hidden");
  document.title = title || "شاشة العرض";
  setTimeout(forcePlay, 1500);
  setTimeout(forcePlay, 3500);
}
function hideVideo(){
  videoFrame.src = "about:blank";
  videoFrame.style.display = "none";
  videoFrame.classList.add("hidden");
}
function animateValue(el, target){
  const dur = 1000, start = performance.now();
  function tick(now){
    const p = Math.min((now-start)/dur, 1);
    const eased = 1 - Math.pow(1-p, 3);
    el.textContent = fmt(target * eased);
    if(p < 1) requestAnimationFrame(tick);
    else el.textContent = fmt(target);
  }
  requestAnimationFrame(tick);
}
function renderStatGrid(container, chart){
  const grid = document.createElement("div");
  grid.className = "stat-grid";
  chart.labels.forEach((label, i) => {
    const val = chart.values[i] || 0;
    const card = document.createElement("div");
    card.className = "stat-card";
    const vEl = document.createElement("div");
    vEl.className = "stat-value";
    const lEl = document.createElement("div");
    lEl.className = "stat-label";
    lEl.textContent = label;
    card.appendChild(vEl);
    card.appendChild(lEl);
    grid.appendChild(card);
    animateValue(vEl, val);
  });
  container.appendChild(grid);
}
function renderBarChart(container, chart){
  const canvas = document.createElement("canvas");
  container.appendChild(canvas);
  new Chart(canvas, {
    type: "bar",
    data: {
      labels: chart.labels,
      datasets: [{
        data: chart.values,
        backgroundColor: chart.labels.map((_,i) => COLORS[i % COLORS.length] + "cc"),
        borderColor: chart.labels.map((_,i) => COLORS[i % COLORS.length]),
        borderWidth: 2, borderRadius: 8, minBarLength: 8,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false },
        tooltip: { callbacks: { label: ctx => fmt(ctx.parsed.y) } } },
      scales: {
        x: { ticks: { color: "#8b98a9", font: { family: "Tajawal", size: 13 } },
             grid: { display: false } },
        y: { ticks: { color: "#8b98a9", callback: v => fmt(v) },
             grid: { color: "#1e293b" } }
      }
    }
  });
}
function renderPieChart(container, chart){
  const canvas = document.createElement("canvas");
  container.appendChild(canvas);
  new Chart(canvas, {
    type: "doughnut",
    data: {
      labels: chart.labels,
      datasets: [{
        data: chart.values,
        backgroundColor: chart.labels.map((_,i) => COLORS[i % COLORS.length]),
        borderColor: "#0a0e1a", borderWidth: 3,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { position: "bottom",
        labels: { color: "#e6edf3", font: { family: "Tajawal", size: 13 }, padding: 12 } } }
    }
  });
}
function renderDashboard(data){
  hideVideo();
  dashTitle.textContent = data.title || "لوحة العرض";
  dashGrid.innerHTML = "";
  const charts = data.charts || [];
  charts.forEach((chart, idx) => {
    const tile = document.createElement("div");
    tile.className = "tile";
    tile.style.animationDelay = (idx * 0.1) + "s";
    const tEl = document.createElement("h3");
    tEl.className = "tile-title";
    tEl.textContent = chart.title || "";
    tile.appendChild(tEl);
    const body = document.createElement("div");
    body.className = "tile-body";
    tile.appendChild(body);
    dashGrid.appendChild(tile);
    if(chart.chart_type === "stat_grid") renderStatGrid(body, chart);
    else if(chart.chart_type === "bar") renderBarChart(body, chart);
    else if(chart.chart_type === "pie") renderPieChart(body, chart);
  });
  idle.classList.add("hidden");
  dash.style.display = "flex";
  dash.classList.remove("hidden");
  document.title = data.title || "شاشة العرض";
}
function showIdle(){
  hideVideo();
  dash.classList.add("hidden");
  dash.style.display = "none";
  idle.classList.remove("hidden");
  document.title = "شاشة العرض";
}
async function poll(){
  try{
    const r = await fetch("/api/display", {cache: "no-store"});
    const d = await r.json();
    dot.style.background = "#22c55e";
    const serial = JSON.stringify(d);
    if(serial !== lastSerial){
      lastSerial = serial;
      if(d.type === "video" && d.url){
        showVideo(d.url, d.title);
      } else if(d.type === "chart" && d.charts && d.charts.length > 0){
        renderDashboard(d);
      } else {
        showIdle();
      }
    }
  }catch(e){
    dot.style.background = "#ef4444";
  }
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


# --- Look-at marker (shared) ------------------------------------------------

_LOOK_AT_LOCK = threading.Lock()
_LOOK_AT_MARKER: dict = {}


def _set_look_at_marker(nx, ny, description, bbox_norm=None):
    with _LOOK_AT_LOCK:
        _LOOK_AT_MARKER["nx"] = float(nx)
        _LOOK_AT_MARKER["ny"] = float(ny)
        _LOOK_AT_MARKER["description"] = description
        _LOOK_AT_MARKER["bbox_norm"] = bbox_norm
        _LOOK_AT_MARKER["timestamp"] = time.monotonic()


def _get_look_at_marker(max_age_s=5.0):
    with _LOOK_AT_LOCK:
        ts = _LOOK_AT_MARKER.get("timestamp", 0)
        if time.monotonic() - ts > max_age_s:
            return None
        return dict(_LOOK_AT_MARKER)


# --- Tool builders (same interface as main.py) ------------------------------

def build_test_tools() -> list:
    return [
        genai_types.Tool(
            function_declarations=[
                genai_types.FunctionDeclaration(
                    name="get_current_time",
                    description="Return the current local time and date.",
                    parameters=genai_types.Schema(type=genai_types.Type.OBJECT, properties={}),
                ),
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
                    name="look_at",
                    description=(
                        "Look at a specific object in the camera view. "
                        "Describe the object and the robot will use "
                        "computer vision to locate it and move its head."
                    ),
                    parameters=genai_types.Schema(
                        type=genai_types.Type.OBJECT,
                        properties={
                            "description": genai_types.Schema(
                                type=genai_types.Type.STRING,
                                description="Description of the object to look at.",
                            ),
                        },
                        required=["description"],
                    ),
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
                    name="show_chart",
                    description=(
                        "Add a chart tile to the dashboard grid on the "
                        "presentation screen. Call multiple times to build "
                        "a multi-chart dashboard. Each call adds one tile. "
                        "Use stat_grid for company key numbers (big animated "
                        "numbers in a grid), bar for comparing companies on "
                        "one metric, pie for showing a breakdown. Labels "
                        "and values must be the same length."
                    ),
                    parameters=genai_types.Schema(
                        type=genai_types.Type.OBJECT,
                        properties={
                            "title": genai_types.Schema(
                                type=genai_types.Type.STRING,
                                description="Chart heading in Arabic, e.g. 'أرقام رافد'.",
                            ),
                            "chart_type": genai_types.Schema(
                                type=genai_types.Type.STRING,
                                enum=["stat_grid", "bar", "pie"],
                                description="stat_grid = big numbers in a grid, bar = comparison chart, pie = breakdown donut",
                            ),
                            "labels": genai_types.Schema(
                                type=genai_types.Type.ARRAY,
                                items=genai_types.Schema(type=genai_types.Type.STRING),
                                description="Labels for each item, same length as values.",
                            ),
                            "values": genai_types.Schema(
                                type=genai_types.Type.ARRAY,
                                items=genai_types.Schema(type=genai_types.Type.NUMBER),
                                description="Numeric values, same length as labels.",
                            ),
                        },
                        required=["title", "chart_type", "labels", "values"],
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


# --- Look-at object detection (OpenRouter Qwen3-VL) -------------------------

def _look_at_object(api_key, jpeg_bytes, description, frame_w, frame_h) -> dict:
    try:
        from openai import OpenAI
        or_key = os.getenv("OPENROUTER_API_KEY", api_key)
        if not or_key:
            return {"found": False, "error": "OPENROUTER_API_KEY not set"}
        client = OpenAI(base_url=OPENROUTER_BASE_URL, api_key=or_key)
        b64 = base64.b64encode(jpeg_bytes).decode("ascii")
        data_url = f"data:image/jpeg;base64,{b64}"
        prompt = (
            f"Locate the {description} in the image. "
            f'Return ONLY JSON: {{"bbox_2d": [x1, y1, x2, y2], "label": "{description}"}} '
            f"using absolute pixel coordinates in an image that is "
            f"{frame_w} pixels wide and {frame_h} pixels tall. "
            f'If not visible, return {{"bbox_2d": null}}.'
        )
        response = client.chat.completions.create(
            model=LOOK_AT_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }],
            max_tokens=128,
            temperature=0.0,
        )
        text = response.choices[0].message.content or ""
        match = re.search(r"\{.*?\}", text, flags=re.DOTALL)
        if not match:
            return {"found": False, "error": "no JSON in response"}
        data = json.loads(match.group(0))
        bbox = data.get("bbox_2d") or data.get("bbox") or data.get("box")
        if not bbox or len(bbox) != 4:
            return {"found": False, "error": "object not visible"}
        x1, y1, x2, y2 = [int(round(v)) for v in bbox]
        if max(x1, y1, x2, y2) <= 1000 and max(frame_w, frame_h) > 1000:
            x1 = int(x1 * frame_w / 1000); x2 = int(x2 * frame_w / 1000)
            y1 = int(y1 * frame_h / 1000); y2 = int(y2 * frame_h / 1000)
        x1 = max(0, min(frame_w - 1, x1)); x2 = max(0, min(frame_w - 1, x2))
        y1 = max(0, min(frame_h - 1, y1)); y2 = max(0, min(frame_h - 1, y2))
        if x2 - x1 < 4 or y2 - y1 < 4:
            return {"found": False, "error": "bbox too small"}
        nx = (x1 + x2) / 2.0 / max(1, frame_w)
        ny = (y1 + y2) / 2.0 / max(1, frame_h)
        return {"found": True, "nx": nx, "ny": ny,
                "bbox_norm": [x1/max(1,frame_w), y1/max(1,frame_h),
                              x2/max(1,frame_w), y2/max(1,frame_h)],
                "confidence": "high", "label": data.get("label", description)}
    except Exception as e:
        return {"found": False, "error": str(e)}


# --- Tool handler -----------------------------------------------------------

def make_tool_handler(
    mini: ReachyMini,
    detector: cv2.FaceDetectorYN,
    recognizer: cv2.FaceRecognizerSF,
    face_db: SimpleFaceDB,
    latest: LatestFrame,
    api_key: str,
    frame_w: int,
    frame_h: int,
    mouth_state: dict,
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
                        "note": "Only videos are supported. Use show_chart for company data."}
            state.set_video(entry.get("url", ""), entry.get("title", ""))
            return {"ok": True, "title": entry.get("title"),
                    "type": "video",
                    "note": "Now playing on the presentation screen."}

        if name == "show_chart":
            title = str(args.get("title", "")).strip() or "رسم بياني"
            chart_type = str(args.get("chart_type", "stat_grid")).strip()
            labels = args.get("labels", [])
            values = args.get("values", [])
            if not isinstance(labels, list) or not isinstance(values, list):
                return {"ok": False, "error": "labels and values must be arrays"}
            if len(labels) != len(values):
                return {"ok": False, "error": "labels and values must be the same length"}
            if len(labels) == 0:
                return {"ok": False, "error": "labels and values cannot be empty"}
            if chart_type not in ("stat_grid", "bar", "pie"):
                return {"ok": False, "error": f"Unknown chart_type: {chart_type}"}
            chart = {
                "title": title,
                "chart_type": chart_type,
                "labels": [str(l) for l in labels],
                "values": [float(v) for v in values],
            }
            state.add_chart(chart)
            return {"ok": True, "title": title, "chart_type": chart_type,
                    "items": len(labels),
                    "note": "Chart added to the dashboard."}

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
        if name == "get_current_time":
            return {"ok": True, "time": time.strftime("%H:%M:%S"),
                    "date": time.strftime("%Y-%m-%d")}

        if name == "ping":
            return {"ok": True, "pong": True}

        if name == "get_robot_status":
            return {"ok": True, "face_recognition": True,
                    "head_tracking": state.tracking_active,
                    "gemini_connected": state.gemini_connected}

        # --- Look at object (OpenRouter Qwen3-VL) ---
        if name == "look_at":
            description = str(args.get("description", "")).strip()
            if not description:
                return {"ok": False, "error": "description is required"}
            jpeg = latest.get_mirrored_jpeg()
            if jpeg is None:
                return {"ok": False, "error": "no camera frame"}

            async def _look_at_task():
                try:
                    result = await asyncio.to_thread(
                        _look_at_object, api_key, jpeg, description, frame_w, frame_h)
                    if not result.get("found"):
                        log.info("look_at: not found: %s", result.get("error"))
                        return
                    nx, ny = result["nx"], result["ny"]
                    _set_look_at_marker(nx, ny, description,
                                        bbox_norm=result.get("bbox_norm"))
                    yaw_deg = (nx - 0.5) * 120.0
                    pitch_deg = (ny - 0.5) * 60.0
                    yaw_deg = max(-60, min(60, yaw_deg))
                    pitch_deg = max(-30, min(30, pitch_deg))
                    _head_to(yaw_deg, pitch_deg)
                    # Auto-resume face follow after 3s
                    await asyncio.sleep(3.0)
                    _resume_face_follow()
                except Exception:
                    log.exception("look_at task failed")

            asyncio.create_task(_look_at_task())
            return {"ok": True, "status": "searching", "description": description}

        return {"ok": False, "error": f"unknown tool: {name}"}

    return handler


# --- Vision loop ------------------------------------------------------------

def draw_overlay(frame, faces, scale, speaker_id, labels, energies):
    """Draw detection boxes + HUD on the frame."""
    h, w = frame.shape[:2]
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

    # Look-at marker
    lam = _get_look_at_marker(max_age_s=5.0)
    if lam:
        lx = int(lam.get("nx", 0.5) * w); ly = int(lam.get("ny", 0.5) * h)
        cv2.line(frame, (lx - 15, ly), (lx + 15, ly), (255, 0, 255), 2)
        cv2.line(frame, (lx, ly - 15), (lx, ly + 15), (255, 0, 255), 2)
        cv2.circle(frame, (lx, ly), 6, (255, 0, 255), 2)
        cv2.putText(frame, f"LOOK: {lam.get('description', '?')}",
                    (lx + 10, ly - 10), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (255, 0, 255), 1, cv2.LINE_AA)

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
            all_tools.extend(build_test_tools())
            if all_tools:
                kwargs["tools"] = all_tools
                kwargs["tool_handler"] = make_tool_handler(
                    mini, detector, recognizer, face_db, latest,
                    api_key, 1280, 720, mouth_state,
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

    # --- Antenna animator ---
    animator = AntennaAnimator()
    anim_last_t = time.time()

    # --- Main loop ---
    try:
        while not stop["flag"]:
            if gemini is not None:
                state.gemini_speaking = gemini.is_speaking.is_set()
            try:
                vision_loop_step(mini, detector, recognizer, face_db, latest, mouth_state)

                # Antenna animation (doesn't conflict with daemon head tracking)
                now_t = time.time()
                dt = now_t - anim_last_t
                anim_last_t = now_t
                r_ant, l_ant = animator.tick(is_talking=state.gemini_speaking, dt=dt)
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

        if gemini is not None:
            print("Stopping Gemini...")
            gemini.stop()

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
