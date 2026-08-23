#!/usr/bin/env python3
"""Local test server for display.html dashboard.

Serves display.html on http://localhost:3000 and provides a mock
/api/display endpoint that returns sample chart data so you can
preview the dashboard UI without the robot.

Usage:
    python3 test_display.py
    # Then open http://localhost:3000/display.html
"""
import json
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent

SAMPLE_CHARTS = {
    "type": "chart",
    "title": "نظرة عامة على مجموعة تطوير التعليم",
    "charts": [
        {
            "title": "أرقام رافد",
            "chart_type": "stat_grid",
            "labels": ["طلاب مستفيدون", "حافلات", "رحلات يومية", "مناطق", "كم/سنة", "مدارس"],
            "values": [740000, 20000, 40000, 13, 122000000, 15000],
        },
        {
            "title": "مقارنة عدد الطلاب",
            "chart_type": "bar",
            "labels": ["رافد", "تطوير للمباني", "التعليمية"],
            "values": [740000, 764000, 6000000],
        },
        {
            "title": "قطاعات التعليمية",
            "chart_type": "pie",
            "labels": ["الطفولة المبكرة", "التربية الخاصة", "التطوير المهني", "الأنشطة الطلابية", "المحتوى الرقمي"],
            "values": [1, 1, 1, 1, 1],
        },
        {
            "title": "أرقام تطوير للمباني",
            "chart_type": "stat_grid",
            "labels": ["منشآت تعليمية", "فصول دراسية", "طاقة استيعابية", "مشاريع روشن"],
            "values": [1573, 25000, 764000, 43],
        },
    ],
}

IDLE_STATE = {"type": "", "url": "", "title": "", "charts": []}

# Cycle: show charts for 15s, then idle for 5s, repeat
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/display":
            t = time.time() % 20
            data = SAMPLE_CHARTS if t < 15 else IDLE_STATE
            payload = json.dumps(data, ensure_ascii=False)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(payload.encode("utf-8"))
        else:
            # Serve static files from project root
            p = self.path.split("?")[0]
            if p == "/":
                p = "/display.html"
            fp = ROOT / p.lstrip("/")
            if fp.exists() and fp.is_file():
                ct = "text/html; charset=utf-8" if p.endswith(".html") else "application/octet-stream"
                self.send_response(200)
                self.send_header("Content-Type", ct)
                self.end_headers()
                self.wfile.write(fp.read_bytes())
            else:
                self.send_response(404)
                self.end_headers()

    def log_message(self, *args):
        pass

if __name__ == "__main__":
    print("Test display server running on http://localhost:3000/display.html")
    print("Cycles: 15s charts → 5s idle → repeat")
    print("Press Ctrl+C to stop")
    server = HTTPServer(("0.0.0.0", 3000), Handler)
    server.serve_forever()
