"""Small web server for the Ingress UI and its JSON API (standard library only).

Security:
- Only the Home Assistant Ingress proxy (172.30.32.2) may connect, unless
  BIFROST_DEV=1 is set for local development.
- Request bodies are limited in size and strictly validated.
- Only static files from the bundled folder are served (no path traversal).
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .categories import STATUSES, is_valid_category, is_valid_role

LOG = logging.getLogger(__name__)
INGRESS_IP = "172.30.32.2"
STATIC = Path(__file__).parent / "static"
MAX_BODY = 4096
MAX_THREADS = 16
REQUEST_TIMEOUT = 10  # seconds per connection
CSRF_HEADER = "X-Bifrost-Request"
ENTITY_RE = re.compile(r"^[a-z_]+\.[a-z0-9_]{1,200}$")
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'self'",
}


def validate_entity_update(body: object) -> tuple[str, str, str | None, str | None]:
    """Validate a POST /api/entity body. Raises ValueError with a safe message."""
    if not isinstance(body, dict):
        raise ValueError("body must be an object")
    eid, status = body.get("entity_id"), body.get("status")
    category, role = body.get("category"), body.get("role")
    if not isinstance(eid, str) or not ENTITY_RE.match(eid):
        raise ValueError("invalid entity_id")
    if status not in STATUSES:
        raise ValueError("invalid status")
    if category is not None and (not isinstance(category, str) or not is_valid_category(category)):
        raise ValueError("invalid category")
    if role is not None and (not isinstance(role, str) or not is_valid_role(role)):
        raise ValueError("invalid role")
    return eid, status, category, role


def make_handler(service, dev: bool = False):  # noqa: ANN001
    class Handler(BaseHTTPRequestHandler):
        server_version = "Bifrost"
        timeout = REQUEST_TIMEOUT
        sys_version = ""

        def log_message(self, fmt: str, *args) -> None:  # noqa: ANN002
            LOG.debug("http: " + fmt, *args)

        # --- helpers -----------------------------------------------------------
        def _allowed(self) -> bool:
            if dev or self.client_address[0] == INGRESS_IP:
                return True
            self._send(HTTPStatus.FORBIDDEN, {"error": "forbidden"})
            return False

        def _send(self, code: HTTPStatus, obj: object, ctype: str = "application/json") -> None:
            data = obj if isinstance(obj, bytes) else json.dumps(obj, ensure_ascii=False, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith(("text", "application/json")) else ""))
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            for k, v in SECURITY_HEADERS.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _route(self) -> str:
            path = self.path.split("?", 1)[0]
            # Ingress strips its prefix; keep only the last meaningful part
            return "/" + path.strip("/")

        # --- methods -------------------------------------------------------------
        def do_GET(self) -> None:  # noqa: N802
            if not self._allowed():
                return
            route = self._route()
            if route in ("/", "/index.html"):
                return self._send(HTTPStatus.OK, (STATIC / "index.html").read_bytes(), "text/html")
            if route == "/favicon.ico":
                self.send_response(HTTPStatus.NO_CONTENT)
                self.end_headers()
                return None
            if route == "/api/status":
                return self._send(HTTPStatus.OK, service.status_view())
            if route == "/api/entities":
                return self._send(HTTPStatus.OK, service.entities_view())
            self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if not self._allowed():
                return
            ctype = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            if ctype != "application/json" or self.headers.get(CSRF_HEADER) != "1":
                return self._send(HTTPStatus.FORBIDDEN, {"error": "missing request header"})
            route = self._route()
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if length < 0 or length > MAX_BODY:
                return self._send(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "body too large"})
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw or b"{}")
            except ValueError:
                return self._send(HTTPStatus.BAD_REQUEST, {"error": "invalid json"})
            if route == "/api/scan":
                service.request_scan()
                return self._send(HTTPStatus.ACCEPTED, {"ok": True})
            if route == "/api/entity":
                try:
                    eid, status, cat, role = validate_entity_update(body)
                    return self._send(HTTPStatus.OK, service.update_entity(eid, status, cat, role))
                except ValueError as err:
                    return self._send(HTTPStatus.BAD_REQUEST, {"error": str(err)})
                except KeyError:
                    return self._send(HTTPStatus.NOT_FOUND, {"error": "unknown entity"})
            self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})

    return Handler


class BoundedThreadingHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer with a hard limit on parallel requests."""

    daemon_threads = True
    max_threads = MAX_THREADS

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self._slots = threading.BoundedSemaphore(self.max_threads)

    def process_request(self, request, client_address) -> None:  # noqa: ANN001
        if not self._slots.acquire(blocking=False):
            try:
                request.sendall(b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address) -> None:  # noqa: ANN001
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


def serve(service, port: int = 8099) -> ThreadingHTTPServer:  # noqa: ANN001
    dev = os.environ.get("BIFROST_DEV") == "1"
    host = "0.0.0.0" if not dev else "127.0.0.1"  # noqa: S104  # nosec B104 – inside the app container, reachable only via Ingress
    httpd = BoundedThreadingHTTPServer((host, port), make_handler(service, dev))
    LOG.info("Web UI listening on %s:%d%s", host, port, " (dev mode)" if dev else "")
    return httpd
