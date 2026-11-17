"""
server.py - Local HTTP bridge between the Chrome extension and the desktop app.

Listens on 127.0.0.1:9632 using only the standard library.
  GET  /ping          -> {"status": "ok"}
  POST /add-download  -> JSON {url, filename, cookies, user_agent, referer, subtitles, ...};
                         emits BridgeSignals.download_requested(dict) which is
                         delivered to the GUI thread via Qt's queued connections.
"""
from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from PySide6.QtCore import QObject, Signal

HOST = "127.0.0.1"
PORT = 9632
MAX_BODY_BYTES = 1024 * 1024
MAX_BATCH_URLS = 5000
MAX_URL_LENGTH = 8192
APP_ID = "CIDM"
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}",
                 f"localhost:{PORT}", "127.0.0.1", "localhost"}


class BridgeSignals(QObject):
    """Thread-safe bridge: emit from any thread, receive in the GUI thread."""
    download_requested = Signal(object)
    batch_requested = Signal(object)
    focus_requested = Signal()
    quit_requested = Signal()


class _BridgeHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows SO_REUSEADDR would let a second instance bind the same port.
    allow_reuse_address = os.name != "nt"

    def __init__(self, address, handler, signals: BridgeSignals):
        super().__init__(address, handler)
        self.signals = signals


class BridgeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "CIDMBridge/1.0"
    timeout = 10

    def log_message(self, fmt, *args):  # keep the console quiet
        pass

    # ----- helpers ---------------------------------------------------------- #
    def _cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Max-Age", "600")

    def _send_json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self._cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # client went away; nothing to do

    def _host_ok(self) -> bool:
        # Blocks DNS-rebinding style requests that use a foreign Host header.
        port = self.server.server_address[1]
        allowed = ALLOWED_HOSTS | {f"127.0.0.1:{port}", f"localhost:{port}"}
        return self.headers.get("Host", "").lower() in allowed

    # ----- verbs ------------------------------------------------------------ #
    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if not self._host_ok():
            return self._send_json(403, {"status": "error", "message": "bad host"})
        if urlparse(self.path).path == "/ping":
            return self._send_json(200, {"status": "ok", "app": APP_ID})
        self._send_json(404, {"status": "error", "message": "not found"})

    def do_POST(self):
        if not self._host_ok():
            return self._send_json(403, {"status": "error", "message": "bad host"})

        req_path = urlparse(self.path).path
        origin = self.headers.get("Origin")

        if req_path == "/focus":
            if hasattr(self.server, "signals") and self.server.signals:
                self.server.signals.focus_requested.emit()
            return self._send_json(200, {"status": "ok", "message": "focused"})

        if req_path == "/quit":
            if origin:
                return self._send_json(403, {"status": "error", "message": "origin not allowed"})
            if hasattr(self.server, "signals") and self.server.signals:
                self.server.signals.quit_requested.emit()
            return self._send_json(200, {"status": "ok", "message": "quitting"})

        # Only the browser extension (or non-browser clients such as curl) may queue downloads.
        if origin and not origin.startswith(("chrome-extension://", "moz-extension://", "extension://", "safari-web-extension://")):
            return self._send_json(403, {"status": "error", "message": "origin not allowed"})
        if req_path not in ("/add-download", "/add-batch"):
            return self._send_json(404, {"status": "error", "message": "not found"})

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length <= 0 or length > MAX_BODY_BYTES:
            return self._send_json(400, {"status": "error", "message": "invalid body length"})
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return self._send_json(400, {"status": "error", "message": "invalid JSON"})
        if not isinstance(data, dict):
            return self._send_json(400, {"status": "error", "message": "expected a JSON object"})

        if req_path == "/add-batch":
            raw_urls = data.get("urls") or []
            if not isinstance(raw_urls, list):
                return self._send_json(400, {"status": "error", "message": "urls must be a list"})
            clean_urls = []
            for u in raw_urls:
                s = str(u).strip()
                if len(s) <= MAX_URL_LENGTH and urlparse(s).scheme.lower() in ("http", "https"):
                    clean_urls.append(s)
                if len(clean_urls) >= MAX_BATCH_URLS:
                    break
            clean_urls = list(dict.fromkeys(clean_urls))  # de-dupe, keep order
            if not clean_urls:
                return self._send_json(400, {"status": "error", "message": "no valid http(s) URLs"})
            batch_payload = {
                "urls": clean_urls,
                "referer": str(data.get("referer") or ""),
                "cookies": str(data.get("cookies") or ""),
                "user_agent": str(data.get("user_agent") or ""),
                "page_title": str(data.get("page_title") or ""),
            }
            if hasattr(self.server, "signals") and self.server.signals:
                self.server.signals.batch_requested.emit(batch_payload)
            return self._send_json(200, {"status": "ok", "count": len(clean_urls)})

        url = str(data.get("url") or "").strip()
        if len(url) > MAX_URL_LENGTH or urlparse(url).scheme.lower() not in ("http", "https"):
            return self._send_json(400, {"status": "error", "message": "only http(s) URLs are supported"})

        kind = str(data.get("kind") or "").strip().lower()
        stream_type = str(data.get("stream_type") or "").strip().lower()
        origin_header = str(data.get("origin") or "").strip()

        raw_subs = data.get("subtitles")
        subtitles = []
        if isinstance(raw_subs, list):
            for sub in raw_subs:
                if isinstance(sub, dict) and sub.get("url"):
                    subtitles.append({
                        "url": str(sub.get("url") or "").strip(),
                        "label": str(sub.get("label") or "Subtitles")[:120],
                        "referer": str(sub.get("referer") or ""),
                        "origin": str(sub.get("origin") or ""),
                        "cookies": str(sub.get("cookies") or ""),
                        "user_agent": str(sub.get("user_agent") or ""),
                    })

        payload = {
            "url": url,
            "filename": str(data.get("filename") or "")[:255],
            "cookies": str(data.get("cookies") or ""),
            "user_agent": str(data.get("user_agent") or ""),
            "referer": str(data.get("referer") or ""),
            "origin": origin_header,
            "stream_type": stream_type,
            "kind": kind or stream_type or "",
            "subtitles": subtitles,
        }
        if hasattr(self.server, "signals") and self.server.signals:
            self.server.signals.download_requested.emit(payload)
        self._send_json(200, {"status": "ok"})


class BridgeServer:
    def __init__(self, signals: BridgeSignals, host: str = HOST, port: int = PORT):
        self._signals = signals
        self._address = (host, port)
        self._httpd = None
        self._thread = None

    def start(self) -> None:
        """Bind and serve in a daemon thread. Raises OSError if the port is taken."""
        self._httpd = _BridgeHTTPServer(
            self._address, BridgeHandler, self._signals)
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, kwargs={"poll_interval": 0.25},
            name="cidm-bridge", daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
