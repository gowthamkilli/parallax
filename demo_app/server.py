"""Local HTTP server for the judge/soldier demo. Static files + 2 tiny JSON
endpoints, localhost only, stdlib http.server -- no new dependency, no real
networking beyond loopback on this one machine.

    python -m demo_app.server [--port 8765]

Then open http://127.0.0.1:8765/judge on the primary display and
http://127.0.0.1:8765/soldier on the second (HDMI) display.
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import state
from .pipeline import CLASSIFIER_PATH, run_scenario, squad_centroid, squad_positions

STATIC_DIR = Path(__file__).parent / "static"

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
}


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, filename: str):
        path = STATIC_DIR / filename
        if not path.exists():
            self.send_response(404)
            self.end_headers()
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", _CONTENT_TYPES.get(path.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        routes = {
            "/": "judge.html",
            "/judge": "judge.html",
            "/soldier": "soldier.html",
            "/style.css": "style.css",
            "/judge.js": "judge.js",
            "/soldier.js": "soldier.js",
        }
        if path in routes:
            self._send_static(routes[path])
        elif path == "/api/state":
            self._send_json(state.get_state())
        elif path == "/api/squad":
            e, n = squad_centroid()
            self._send_json({"nodes": squad_positions(), "centroid": {"e": e, "n": n}})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if urlparse(self.path).path != "/api/run":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length))
            result = run_scenario(
                enemy_e=float(payload["e"]),
                enemy_n=float(payload["n"]),
                category=str(payload["category"]),
            )
            state.add_result(result)
            self._send_json(result)
        except Exception as exc:  # noqa: BLE001 -- report to the caller, don't crash the server
            self._send_json({"error": str(exc)}, status=400)

    def log_message(self, format, *args):  # noqa: A002 -- stdlib signature
        pass  # keep the console quiet during a live demo


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    state.load()
    if not CLASSIFIER_PATH.exists():
        print(f"[warn] {CLASSIFIER_PATH} not found -- run `python -m sim.train_classifier` first. "
              "Proceeding with the stub classifier (GUNSHOT, confidence 0.75).")

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"PARALLAX judge/soldier demo running on 127.0.0.1:{args.port}")
    print(f"  Judge screen:   http://127.0.0.1:{args.port}/judge")
    print(f"  Soldier screen: http://127.0.0.1:{args.port}/soldier")
    print("Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
