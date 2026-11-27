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
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from .categories import STATUSES, is_valid_category, is_valid_role

LOG = logging.getLogger(__name__)
INGRESS_IP = "172.30.32.2"
STATIC = Path(__file__).parent / "static"
MAX_BODY = 4096
FLOORPLAN_BODY = 3_000_000  # base64 of a 2 MB picture
LAYOUT_BODY = 32_768  # up to 864 painted cells
MAP_BODY = 65_536  # house map 2.0: rectangles, marks and placed devices
FLOOR_KEY_RE = re.compile(r"^[a-z0-9_]{1,40}$")
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


def validate_guest(body: object) -> bool:
    if not isinstance(body, dict) or not isinstance(body.get("on"), bool):
        raise ValueError("on must be true or false")
    return body["on"]


def _entity(body: dict, key: str = "entity_id") -> str:
    v = body.get(key)
    if not isinstance(v, str) or not ENTITY_RE.match(v):
        raise ValueError("invalid entity_id")
    return v


def _str(body: dict, key: str, maxlen: int = 80) -> str:
    v = body.get(key)
    if not isinstance(v, str) or not v or len(v) > maxlen:
        raise ValueError(f"{key} missing or too long")
    return v


VIEWS = {
    "/api/i18n": "i18n_view",
    "/api/live": "live_view",
    "/api/optimizations": "optimizations_view",
    "/api/sources": "sources_view",
    "/api/correct/candidates": "correct_candidates",
    "/api/people": "people_view",
    "/api/house": "house_view",
    "/api/recognition": "recognition_view",
    "/api/questions": "questions_view",
    "/api/balance": "balance_view",
    "/api/catalog": "catalog_view",
    "/api/notify": "notify_view",
    "/api/incidents": "incidents_view",
}

ACTIONS = {
    "/api/person": lambda svc, b: svc.save_person(b if isinstance(b, dict) else {}),
    "/api/person/delete": lambda svc, b: svc.delete_person(_str(b, "id", 40)),
    "/api/optimization/dismiss": lambda svc, b: svc.dismiss_optimization(_entity(b), _str(b, "key", 30)),
    "/api/optimization/reset": lambda svc, b: svc.reset_optimizations(),
    "/api/owner": lambda svc, b: svc.set_owner(b.get("entity_id"), b.get("owner")),
    "/api/access_map": lambda svc, b: svc.brain.people.map_access(b.get("value"), b.get("target")),
    "/api/irk/delete_all": lambda svc, b: svc.brain.people.delete_all_irks(),
    "/api/answer": lambda svc, b: svc.answer(_str(b, "id", 40), _str(b, "answer", 10), b.get("label") if isinstance(b.get("label"), str) else None),
    "/api/correct": lambda svc, b: svc.correct(
        _str(b, "actual", 10),
        _entity(b, "culprit") if b.get("culprit") else None,
        _str(b, "person", 40) if b.get("person") else None,
    ),
    "/api/exception/delete": lambda svc, b: {"deleted": svc.brain.inbox.remove_exception(_str(b, "sensor", 255))},
    "/api/floorplan": lambda svc, b: svc.set_floorplan(b),
    "/api/floorplan/delete": lambda svc, b: svc.delete_floorplan(b.get("floor"), b.get("layer", 0)),
    "/api/layout": lambda svc, b: svc.set_layout(b),
    "/api/layout/reset": lambda svc, b: svc.reset_layout(b.get("floor")),
    "/api/map": lambda svc, b: svc.set_map(b),
    "/api/map/reset": lambda svc, b: svc.reset_map(b.get("floor")),
    "/api/pattern_entity": lambda svc, b: svc.set_pattern_entity(b),
    "/api/entities/seen": lambda svc, b: svc.mark_seen(b.get("entity_id")),
    "/api/notify": lambda svc, b: svc.set_notify(b.get("target")),
    "/api/notify/test": lambda svc, b: svc.test_notification(),
}


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

        def _read_body(self, limit: int = 0) -> bytes:
            """Read the request body – with Content-Length or chunked (HA Ingress streams bodies chunked)."""
            if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
                data = b""
                while True:
                    line = self.rfile.readline(64)
                    try:
                        size = int(line.split(b";", 1)[0].strip() or b"0", 16)
                    except ValueError as err:
                        raise ValueError("bad chunk") from err
                    if size == 0:
                        self.rfile.readline(64)  # trailing CRLF
                        break
                    if len(data) + size > (limit or MAX_BODY):
                        raise ValueError("too large")
                    data += self.rfile.read(size)
                    self.rfile.read(2)  # CRLF after each chunk
                return data or b"{}"
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError as err:
                raise ValueError("bad length") from err
            if length < 0 or length > (limit or MAX_BODY):
                raise ValueError("too large")
            return self.rfile.read(length) if length else b"{}"

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
            if route == "/api/calendars":
                return self._send(HTTPStatus.OK, service.calendars_view())
            view = VIEWS.get(route)
            if view and hasattr(service, view):
                return self._send(HTTPStatus.OK, getattr(service, view)())
            if route == "/api/entity_detail":
                query = parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
                eid = (query.get("entity_id") or [""])[0]
                if not ENTITY_RE.match(eid):
                    return self._send(HTTPStatus.BAD_REQUEST, {"error": "invalid entity_id"})
                try:
                    return self._send(HTTPStatus.OK, service.entity_detail(eid))
                except KeyError:
                    return self._send(HTTPStatus.NOT_FOUND, {"error": "unknown entity"})
            if route == "/api/floorplan":
                query = parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
                key = (query.get("floor") or [""])[0]
                if key and not FLOOR_KEY_RE.match(key):
                    return self._send(HTTPStatus.BAD_REQUEST, {"error": "invalid floor"})
                fp = service.brain.floorplan_bytes(key)
                if not fp:
                    return self._send(HTTPStatus.NOT_FOUND, {"error": "no floor plan"})
                return self._send(HTTPStatus.OK, fp[0], fp[1])
            self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if not self._allowed():
                return
            ctype = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            if ctype != "application/json" or self.headers.get(CSRF_HEADER) != "1":
                return self._send(HTTPStatus.FORBIDDEN, {"error": "missing request header"})
            route = self._route()
            try:
                raw = self._read_body(FLOORPLAN_BODY if route == "/api/floorplan" else LAYOUT_BODY if route == "/api/layout" else MAP_BODY if route == "/api/map" else MAX_BODY)
            except ValueError:
                return self._send(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "body too large"})
            try:
                body = json.loads(raw or b"{}")
            except ValueError:
                return self._send(HTTPStatus.BAD_REQUEST, {"error": "invalid json"})
            if route == "/api/scan":
                service.request_scan()
                return self._send(HTTPStatus.ACCEPTED, {"ok": True})
            if route == "/api/learn":
                service.learn_job(datetime.now(UTC))
                return self._send(HTTPStatus.OK, {"ok": True})
            if route == "/api/language":
                try:
                    return self._send(HTTPStatus.OK, service.set_language(_str(body, "language", 2)))
                except ValueError as err:
                    return self._send(HTTPStatus.BAD_REQUEST, {"error": str(err)})
            if route == "/api/guest":
                try:
                    return self._send(HTTPStatus.OK, service.set_guest_mode(validate_guest(body)))
                except ValueError as err:
                    return self._send(HTTPStatus.BAD_REQUEST, {"error": str(err)})
            if route in ACTIONS:
                try:
                    return self._send(HTTPStatus.OK, ACTIONS[route](service, body))
                except ValueError as err:
                    return self._send(HTTPStatus.BAD_REQUEST, {"error": str(err)[:200]})
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
