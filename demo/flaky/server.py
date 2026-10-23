"""A tiny web service you can break on purpose, so NetScope has outages to detect.

    GET  /health          the endpoint NetScope monitors
    GET  /                current mode
    POST /mode/<mode>     switch mode: up | down | slow | flaky

Modes:
    up     200 OK after 20-80 ms
    down   503 Service Unavailable
    slow   200 OK after 1.5-3 s (watch p95 climb)
    flaky  fails about 40% of requests

Standard library only, so the container needs nothing installed.
"""

from __future__ import annotations

import json
import os
import random
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODES = {"up", "down", "slow", "flaky"}
state = {"mode": os.getenv("FLAKY_MODE", "up")}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/":
            return self._send(200, {"mode": state["mode"], "modes": sorted(MODES)})
        if self.path != "/health":
            return self._send(404, {"error": "not found"})

        mode = state["mode"]
        if mode == "down":
            return self._send(503, {"status": "down"})
        if mode == "slow":
            time.sleep(random.uniform(1.5, 3.0))
        else:
            time.sleep(random.uniform(0.02, 0.08))
        if mode == "flaky" and random.random() < 0.4:
            return self._send(500, {"status": "error"})
        return self._send(200, {"status": "ok"})

    def do_POST(self) -> None:  # noqa: N802
        mode = self.path.removeprefix("/mode/")
        if not self.path.startswith("/mode/") or mode not in MODES:
            return self._send(400, {"error": f"use POST /mode/<{'|'.join(sorted(MODES))}>"})
        state["mode"] = mode
        print(f"mode -> {mode}", flush=True)
        return self._send(200, {"mode": mode})

    def log_message(self, fmt: str, *args) -> None:  # keep container logs quiet
        pass


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    print(f"flaky demo service on :{port}, mode={state['mode']}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
