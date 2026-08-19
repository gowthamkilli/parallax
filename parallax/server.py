"""Minimal local HTTP bridge so a browser can call the real algorithm.

Wraps parallax.api (process_node_report / process_network) behind a tiny
JSON API using only the standard library -- no new dependencies, runs fully
offline. This is the one piece of "front end talks to backend" plumbing;
everything either side of the wire already existed (api.py's docstring
even says "for the (future) JavaScript front end").

    python -m parallax.server            # serves on :8787

Endpoints
---------
    GET  /api/health    -> {"ok": true}
    POST /api/node       body: process_node_report's input schema
    POST /api/network     body: process_network's input schema

Both POST endpoints return exactly what parallax.api returns: either
{"ok": true, "fix": {...}} or {"ok": false, "error": "..."}.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .api import process_network, process_node_report

DEFAULT_PORT = 8787


class Handler(BaseHTTPRequestHandler):
    server_version = "ParallaxGDS/0.1"

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802 -- BaseHTTPRequestHandler naming
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/health":
            self._send_json(200, {"ok": True, "service": "parallax-gds"})
            return
        if self.path == "/":
            self._send_json(200, {
                "ok": True,
                "service": "parallax-gds",
                "note": "this is the algorithm bridge, not a page -- the UI is the Vite frontend at :5173",
                "endpoints": {
                    "GET /api/health": "liveness check",
                    "POST /api/node": "process_node_report(payload)",
                    "POST /api/network": "process_network(payload)",
                },
            })
            return
        self._send_json(404, {"ok": False, "error": f"no route for GET {self.path}"})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw or b"{}")
        except json.JSONDecodeError as exc:
            self._send_json(400, {"ok": False, "error": f"bad JSON: {exc}"})
            return

        if self.path == "/api/node":
            self._send_json(200, process_node_report(payload))
            return
        if self.path == "/api/network":
            self._send_json(200, process_network(payload))
            return
        self._send_json(404, {"ok": False, "error": f"no route for POST {self.path}"})

    def log_message(self, fmt: str, *args) -> None:  # quieter default logging
        print(f"[gds-backend] {self.address_string()} {fmt % args}")


def serve(port: int = DEFAULT_PORT) -> None:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"[gds-backend] parallax algorithm bridge listening on http://127.0.0.1:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    serve()
