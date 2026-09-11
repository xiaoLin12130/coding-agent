"""Deterministic local chat page used to exercise the browser driver offline.

Run it for a manual demo:

    cd backend
    python -m fixtures.chat_site.server --port 8765

Query parameters understood by the page:

* mode=normal : streams a complete reply and finishes.
* mode=stuck  : starts streaming and never finishes (timeout-fallback test).
* login=1     : shows a login wall until the sign-in button is clicked.

This is a fixture, not a provider: no real LLM is involved.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

INDEX = Path(__file__).with_name("index.html")
CHUNK_DELAY_S = 0.08
STUCK_MAX_S = 30.0


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *args) -> None:  # keep test output clean
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            body = INDEX.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/api/chat":
            self._stream_chat(parse_qs(parsed.query))
            return
        self.send_error(404)

    def _write_raw(self, payload: bytes) -> None:
        self.wfile.write(payload)
        self.wfile.flush()

    def _write_event(self, payload: dict) -> None:
        self._write_raw(b"data: " + json.dumps(payload).encode("utf-8") + b"\n\n")

    def _stream_chat(self, query: dict) -> None:
        prompt = (query.get("prompt") or [""])[0]
        mode = (query.get("mode") or ["normal"])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        reply = f"Fixture reply to: {prompt}"
        chunks = [reply[i : i + 6] for i in range(0, len(reply), 6)] or [""]

        try:
            if mode == "stuck":
                # Two chunks, then keep the stream open: the page keeps its
                # Stop button visible and the text stops changing, so a driver
                # that ignored the stop signal would wrongly report completion.
                for chunk in chunks[:2]:
                    self._write_event({"delta": chunk})
                    time.sleep(CHUNK_DELAY_S)
                deadline = time.monotonic() + STUCK_MAX_S
                while time.monotonic() < deadline:
                    time.sleep(0.5)
                    self._write_event({"delta": ""})
                return

            for chunk in chunks:
                self._write_event({"delta": chunk})
                time.sleep(CHUNK_DELAY_S)
            self._write_event({"done": True})
            self._write_raw(b"data: [DONE]\n\n")
        except (BrokenPipeError, ConnectionResetError, OSError):
            return


class FixtureSite:
    """Threaded fixture server; port 0 picks a free port."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        self.host = host
        self._httpd = _Server((host, port), _Handler)
        self.port = int(self._httpd.server_address[1])
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    def start(self) -> "FixtureSite":
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="fixture-site", daemon=True
        )
        self._thread.start()
        return self

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def __enter__(self) -> "FixtureSite":
        return self.start()

    def __exit__(self, *exc_info: object) -> None:
        self.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the fixture chat page")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    site = FixtureSite(args.host, args.port).start()
    print(f"fixture chat site: {site.base_url}")
    print("open it, or run: python -m app.browser.cli ask --profile mock --prompt hi")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        site.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
