"""Minimal Home Assistant client using only the Python standard library.

Inside the app the Supervisor provides SUPERVISOR_TOKEN and proxies the
Core API at http://supervisor/core. For local development HA_URL and HA_TOKEN
can be set instead. The token is never logged.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import socket
import struct
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import Any

from .live import origin_of

LOG = logging.getLogger(__name__)
MAX_FRAME = 64 * 1024 * 1024  # registries of large installations are a few MB


class HAError(RuntimeError):
    pass


S6_ENV_DIR = "/run/s6/container_environment"


def _read_s6_env(name: str) -> str | None:
    """Fallback: s6-overlay keeps the container environment as files."""
    try:
        with open(os.path.join(S6_ENV_DIR, name), encoding="utf-8") as fh:
            return fh.read().strip() or None
    except OSError:
        return None


class HAClient:
    def __init__(self, base_url: str | None = None, token: str | None = None, timeout: float = 20) -> None:
        sup = os.environ.get("SUPERVISOR_TOKEN") or _read_s6_env("SUPERVISOR_TOKEN")
        self.base_url = (base_url or os.environ.get("HA_URL") or ("http://supervisor/core" if sup else "http://localhost:8123")).rstrip("/")
        self._token = token or os.environ.get("HA_TOKEN") or sup or ""
        self.timeout = timeout
        if not self._token:
            raise HAError("No Home Assistant token available")

    # --- REST ----------------------------------------------------------------
    def _request(self, method: str, path: str, body: dict | None = None) -> Any:
        url = f"{self.base_url}/api/{path.lstrip('/')}"
        if not url.startswith(("http://", "https://")):
            raise HAError("Only http(s) URLs are allowed")
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)  # noqa: S310 – scheme checked above
        req.add_header("Authorization", f"Bearer {self._token}")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 – scheme checked above  # nosec B310
                raw = resp.read()
        except Exception as err:  # noqa: BLE001
            raise HAError(f"{method} {path} failed: {type(err).__name__}") from None
        ctype = resp.headers.get("Content-Type", "")
        return json.loads(raw) if "json" in ctype else raw.decode()

    def get_config(self) -> dict:
        return self._request("GET", "config")

    def get_states(self) -> list[dict]:
        return self._request("GET", "states")

    def set_state(self, entity_id: str, state: str, attributes: dict) -> None:
        self._request("POST", f"states/{urllib.parse.quote(entity_id)}", {"state": state, "attributes": attributes})

    def delete_state(self, entity_id: str) -> None:
        """Remove a state that was written with POST /api/states (clean-up after the switch to MQTT)."""
        self._request("DELETE", f"states/{urllib.parse.quote(entity_id)}")

    def mqtt_service(self) -> dict | None:
        """Broker credentials from the Supervisor (services: mqtt:want) – None when there is no broker."""
        token = os.environ.get("SUPERVISOR_TOKEN") or _read_s6_env("SUPERVISOR_TOKEN")
        if not token:
            return None
        req = urllib.request.Request("http://supervisor/services/mqtt", method="GET")  # noqa: S310 – fixed internal URL
        req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 – fixed internal URL  # nosec B310
                data = json.loads(resp.read()).get("data") or {}
        except Exception:  # noqa: BLE001 – no broker installed is fine
            return None
        return data if data.get("host") else None

    def get_calendar(self, entity_id: str, start: str, end: str) -> list[dict]:
        """Calendar entries between start and end (ISO). Titles are only used in memory."""
        if not entity_id.startswith("calendar.") or not entity_id.replace("_", "a").replace(".", "a").isalnum():
            raise HAError("invalid calendar entity")
        q = urllib.parse.urlencode({"start": start, "end": end})
        res = self._request("GET", f"calendars/{urllib.parse.quote(entity_id)}?{q}")
        return res if isinstance(res, list) else []

    def notify_services(self) -> list[str]:
        """Names of the notify services Home Assistant offers (e.g. mobile_app_<phone>)."""
        res = self._request("GET", "services")
        for d in res if isinstance(res, list) else []:
            if d.get("domain") == "notify":
                return sorted(str(k) for k in (d.get("services") or {}))
        return []

    def notify(self, service: str, title: str, message: str) -> None:
        """Send a notification through notify.<service>. The service name is checked by the caller."""
        if not service.replace("_", "a").isalnum():
            raise HAError("invalid notify service")
        self._request("POST", f"services/notify/{urllib.parse.quote(service)}", {"title": title[:100], "message": message[:500]})

    def get_history(self, entity_id: str, start: str, end: str) -> list[dict]:
        """State history of one entity between start and end (ISO), minimal – for the entity detail in Setup."""
        q = urllib.parse.urlencode({"filter_entity_id": entity_id, "end_time": end, "minimal_response": "", "no_attributes": ""})
        res = self._request("GET", f"history/period/{urllib.parse.quote(start)}?{q}")
        return res[0] if isinstance(res, list) and res and isinstance(res[0], list) else []

    # --- WebSocket (registries) ------------------------------------------------
    def registries(self) -> dict[str, list[dict]]:
        """Read entity, device and area registries via the WebSocket API."""
        ws = _SimpleWebSocket(self._ws_url(), self.timeout)
        try:
            hello = ws.recv_json()
            if hello.get("type") != "auth_required":
                raise HAError("Unexpected WebSocket greeting")
            ws.send_json({"type": "auth", "access_token": self._token})
            if ws.recv_json().get("type") != "auth_ok":
                raise HAError("WebSocket authentication failed")
            out: dict[str, list[dict]] = {}
            for i, (key, cmd) in enumerate(
                (
                    ("entities", "config/entity_registry/list"),
                    ("devices", "config/device_registry/list"),
                    ("areas", "config/area_registry/list"),
                    ("floors", "config/floor_registry/list"),
                ),
                start=1,
            ):
                ws.send_json({"id": i, "type": cmd})
                msg = ws.recv_json()
                if not msg.get("success"):
                    if key == "floors":  # floors exist since HA 2024.4 – optional
                        out[key] = []
                        continue
                    raise HAError(f"{cmd} failed")
                out[key] = msg.get("result") or []
            return out
        finally:
            ws.close()

    def stream_state_changes(self, on_change, stop, on_connected=None, idle_seconds: float = 30) -> None:  # noqa: ANN001
        """Subscribe to state_changed and call on_change(entity_id, state, ts) until stop is set.

        Returns when stop is set; raises HAError/OSError on connection problems (the caller reconnects).
        """
        ws = _SimpleWebSocket(self._ws_url(), self.timeout)
        try:
            hello = ws.recv_json()
            if hello.get("type") != "auth_required":
                raise HAError("Unexpected WebSocket greeting")
            ws.send_json({"type": "auth", "access_token": self._token})
            if ws.recv_json().get("type") != "auth_ok":
                raise HAError("WebSocket authentication failed")
            ws.send_json({"id": 1, "type": "subscribe_events", "event_type": "state_changed"})
            msg = ws.recv_json()
            if not msg.get("success"):
                raise HAError("Subscribing to state changes failed")
            if on_connected:
                on_connected()
            ws.sock.settimeout(idle_seconds)
            next_id = 2
            while not stop.is_set():
                try:
                    msg = ws.recv_json()
                except TimeoutError:
                    ws.send_json({"id": next_id, "type": "ping"})  # keep the connection alive
                    next_id += 1
                    continue
                change = parse_state_changed(msg)
                if change:
                    on_change(*change, origin=origin_of(msg), attrs=identity_attrs(msg))
        finally:
            ws.close()

    def stream_bluetooth(self, on_adverts, stop, on_connected=None, on_scanners=None, idle_seconds: float = 30) -> None:  # noqa: ANN001, C901
        """Subscribe to HA's Bluetooth advertisements (and scanner names) until stop is set.

        Raises HAError("not supported") when this Home Assistant has no advertisement subscription.
        """
        ws = _SimpleWebSocket(self._ws_url(), self.timeout)
        try:
            if ws.recv_json().get("type") != "auth_required":
                raise HAError("Unexpected WebSocket greeting")
            ws.send_json({"type": "auth", "access_token": self._token})
            if ws.recv_json().get("type") != "auth_ok":
                raise HAError("WebSocket authentication failed")
            ws.send_json({"id": 1, "type": "bluetooth/subscribe_advertisements"})
            ws.send_json({"id": 2, "type": "bluetooth/subscribe_scanner_details"})
            ws.sock.settimeout(idle_seconds)
            next_id, ok = 3, False
            while not stop.is_set():
                try:
                    msg = ws.recv_json()
                except TimeoutError:
                    ws.send_json({"id": next_id, "type": "ping"})
                    next_id += 1
                    continue
                mid = msg.get("id")
                if msg.get("type") == "result":
                    if mid == 1 and not msg.get("success"):
                        raise HAError("not supported")
                    if mid == 1 and not ok:
                        ok = True
                        if on_connected:
                            on_connected()
                    continue
                ev = msg.get("event") if msg.get("type") == "event" else None
                if not isinstance(ev, dict):
                    continue
                if mid == 1:
                    adds = ev.get("add") or []
                    if isinstance(adds, list):
                        on_adverts(adds)
                elif mid == 2 and on_scanners:
                    rows = ev.get("add") or ev.get("scanners") or []
                    if isinstance(rows, list):
                        on_scanners({str(r.get("source", "")): str(r.get("name", "")) for r in rows if isinstance(r, dict) and r.get("source")})
        finally:
            ws.close()

    def _ws_url(self) -> str:
        u = urllib.parse.urlparse(self.base_url)
        path = "/core/websocket" if os.environ.get("SUPERVISOR_TOKEN") and not os.environ.get("HA_URL") else "/api/websocket"
        if u.path and u.path not in ("/", "/core"):
            path = u.path.rstrip("/") + "/api/websocket"
        return urllib.parse.urlunparse((u.scheme, u.netloc, path, "", "", ""))


class _SimpleWebSocket:
    """Just enough RFC 6455 for request/response JSON over ws:// (local only)."""

    def __init__(self, url: str, timeout: float) -> None:
        u = urllib.parse.urlparse(url)
        if u.scheme != "http":
            raise HAError("Only local http WebSocket connections are supported")
        host, port = u.hostname or "localhost", u.port or 80
        self.sock = socket.create_connection((host, port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = f"GET {u.path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        self.sock.sendall(req.encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(1024)
            if not chunk:
                raise HAError("WebSocket handshake failed")
            head += chunk
        status, _, rest = head.partition(b"\r\n\r\n")
        if b" 101 " not in status.split(b"\r\n", 1)[0]:
            raise HAError("WebSocket upgrade refused")
        self._buf = rest
        self._in_frame = False

    def _read(self, n: int) -> bytes:
        while len(self._buf) < n:
            try:
                chunk = self.sock.recv(65536)
            except TimeoutError:
                if self._in_frame or self._buf:
                    raise HAError("WebSocket stalled in the middle of a message") from None
                raise
            if not chunk:
                raise HAError("WebSocket closed")
            self._buf += chunk
        data, self._buf = self._buf[:n], self._buf[n:]
        return data

    def send_json(self, obj: dict) -> None:
        self.sock.sendall(encode_frame(json.dumps(obj).encode()))

    def recv_json(self) -> dict:
        payload = b""
        while True:
            self._in_frame = bool(payload)
            b1, b2 = self._read(2)
            self._in_frame = True
            fin, opcode, length = b1 & 0x80, b1 & 0x0F, b2 & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._read(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._read(8))[0]
            if b2 & 0x80:
                raise HAError("Server frames must not be masked")
            if len(payload) + length > MAX_FRAME:
                raise HAError("WebSocket message too large")
            data = self._read(length)
            if opcode == 0x8:
                raise HAError("WebSocket closed by server")
            if opcode == 0x9:  # ping → pong
                self.sock.sendall(encode_frame(data, opcode=0xA))
                continue
            payload += data
            if fin:
                self._in_frame = False
                return json.loads(payload)

    def close(self) -> None:
        try:
            self.sock.sendall(encode_frame(b"", opcode=0x8))
        except OSError:
            pass
        self.sock.close()


IDENTITY_ATTRS = ("changed_by", "user", "user_name", "username", "user_id", "code_slot_name", "code_name", "last_user", "name")


def identity_attrs(msg: dict) -> dict:
    """Only the few attributes that can say who unlocked (smart locks, keypads) – nothing else is kept."""
    attrs = (((msg.get("event") or {}).get("data") or {}).get("new_state") or {}).get("attributes") or {}
    return {k: str(attrs[k])[:40] for k in IDENTITY_ATTRS if attrs.get(k) not in (None, "")}


def parse_state_changed(msg: dict) -> tuple[str, str | None, datetime] | None:
    """Extract (entity_id, new state, change time) from a state_changed event message."""
    if msg.get("type") != "event":
        return None
    data = (msg.get("event") or {}).get("data") or {}
    eid = data.get("entity_id")
    new = data.get("new_state") or {}
    if not isinstance(eid, str) or not eid:
        return None
    ts_raw = new.get("last_changed") or (msg.get("event") or {}).get("time_fired")
    try:
        ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
    except ValueError:
        ts = datetime.now(UTC)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    state = new.get("state") if new else None
    return eid, (str(state) if state is not None else None), ts


def encode_frame(payload: bytes, opcode: int = 0x1) -> bytes:
    """Encode one masked client frame (RFC 6455 §5.2)."""
    head = bytes([0x80 | opcode])
    n = len(payload)
    if n < 126:
        head += bytes([0x80 | n])
    elif n < 65536:
        head += bytes([0x80 | 126]) + struct.pack(">H", n)
    else:
        head += bytes([0x80 | 127]) + struct.pack(">Q", n)
    mask = os.urandom(4)
    return head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
