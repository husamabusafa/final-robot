#!/usr/bin/env python3
"""Replay a scripted dashboard build against the panel relay.

Lets you iterate on the panel UI without the robot, and exercises exactly the
path main_pi.py will use: connect to /robot with a token, then push one
incremental event at a time.

Usage:
    python3 scripts/simulate.py                  # loop the whole scenario
    python3 scripts/simulate.py --once           # one pass, then exit
    python3 scripts/simulate.py --delay 0.4      # faster tile-by-tile build
    python3 scripts/simulate.py --url wss://panel.example.com/robot --token ...
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import ssl
import sys

import websockets

try:
    import certifi
except ImportError:  # pragma: no cover - certifi ships with pip's deps
    certifi = None


def ws_kwargs(url: str) -> dict:
    """macOS Pythons lack system root CAs; give wss:// an explicit bundle."""
    if url.startswith("wss://") and certifi is not None:
        return {"ssl": ssl.create_default_context(cafile=certifi.where())}
    return {}

DEFAULT_URL = os.environ.get("PANEL_URL", "ws://localhost:4001/robot")
DEFAULT_TOKEN = os.environ.get("HSAFA_PANEL_TOKEN", "dev-token")

DASHBOARD_TITLE = "نظرة عامة على مجموعة تطوير التعليم"

TILES = [
    {
        "id": "sim-rafed-kpi",
        "type": "kpi",
        "title": "أرقام رافد",
        "labels": ["طلاب مستفيدون", "حافلات", "رحلات يومية", "مناطق", "كم/سنة", "مدارس"],
        "values": [740000, 20000, 40000, 13, 122000000, 15000],
    },
    {
        "id": "sim-students-bar",
        "type": "bar",
        "title": "مقارنة عدد الطلاب",
        "labels": ["رافد", "تطوير للمباني", "التعليمية"],
        "values": [740000, 764000, 6000000],
        "unit": "طالب",
    },
    {
        "id": "sim-talimia-pie",
        "type": "pie",
        "title": "قطاعات التعليمية",
        "labels": ["الطفولة المبكرة", "التربية الخاصة", "التطوير المهني", "الأنشطة الطلابية", "المحتوى الرقمي"],
        "values": [22, 18, 25, 15, 20],
        "unit": "%",
    },
    {
        "id": "sim-buildings-line",
        "type": "line",
        "title": "نمو المنشآت التعليمية",
        "labels": ["2021", "2022", "2023", "2024", "2025"],
        "values": [420, 690, 980, 1280, 1573],
        "unit": "منشأة",
    },
    {
        "id": "sim-tetco-table",
        "type": "table",
        "title": "منصات تيتكو",
        "labels": ["مدرستي", "روضتي", "قدرات", "بوابة المستقبل"],
        "textValues": ["التعليم عن بعد", "الطفولة المبكرة", "قياس المهارات", "التحول الرقمي"],
    },
]

VIDEO = {
    "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "title": "حملة حافلتي الصفراء",
}


async def send(ws, event: dict) -> None:
    await ws.send(json.dumps({"v": 1, **event}, ensure_ascii=False))
    print(f"  -> {event['type']}" + (f" {event['tile']['title']}" if "tile" in event else ""))


async def scenario(ws, delay: float) -> None:
    await send(ws, {"type": "robot.status", "online": True, "speaking": False})

    print("dashboard: building tile by tile")
    await send(ws, {"type": "dashboard.begin", "title": DASHBOARD_TITLE})
    for tile in TILES:
        await asyncio.sleep(delay)
        await send(ws, {"type": "dashboard.tile", "tile": tile})

    await asyncio.sleep(delay * 6)
    print("video")
    await send(ws, {"type": "video.show", **VIDEO})

    await asyncio.sleep(delay * 6)
    print("idle")
    await send(ws, {"type": "display.clear"})
    await asyncio.sleep(delay * 3)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--token", default=DEFAULT_TOKEN)
    ap.add_argument("--delay", type=float, default=1.2,
                    help="seconds between tiles (default 1.2)")
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()

    url = args.url + ("&" if "?" in args.url else "?") + f"token={args.token}"
    print(f"connecting to {args.url}")
    try:
        async with websockets.connect(url, **ws_kwargs(args.url)) as ws:
            print("connected")
            while True:
                await scenario(ws, args.delay)
                if args.once:
                    return 0
    except OSError as e:
        print(f"could not connect: {e}")
        return 1
    except (websockets.exceptions.InvalidStatus,
            websockets.exceptions.ConnectionClosed) as e:
        print(f"rejected by relay: {e} (wrong token?)")
        return 1


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\nstopped")
