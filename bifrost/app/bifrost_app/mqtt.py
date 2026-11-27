"""Minimal MQTT 3.1.1 client (0.12) – standard library only.

Just what Bifrost needs to publish Home Assistant MQTT Discovery entities:

* CONNECT with user/password and a Last Will (retained "offline" on the availability topic),
* PUBLISH QoS 0 / 1 with retain, PUBACK,
* SUBSCRIBE (for ``homeassistant/status``) and incoming PUBLISH,
* PINGREQ keep-alive, DISCONNECT,
* a background thread that reconnects with back-off and calls ``on_connect`` after every (re)connect.

No TLS: the broker is reached on the Supervisor's internal network.
"""

from __future__ import annotations

import logging
import socket
import struct
import threading
import time
from collections.abc import Callable

LOG = logging.getLogger(__name__)

CONNECT, CONNACK, PUBLISH, PUBACK, SUBSCRIBE, SUBACK, PINGREQ, PINGRESP, DISCONNECT = 1, 2, 3, 4, 8, 9, 12, 13, 14
MAX_PACKET = 256 * 1024


class MQTTError(Exception):
    pass


def encode_length(n: int) -> bytes:
    """MQTT variable length (1–4 bytes)."""
    if n < 0 or n > 268_435_455:
        raise MQTTError("packet too large")
    out = bytearray()
    while True:
        byte, n = n % 128, n // 128
        out.append(byte | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _str(s: str) -> bytes:
    b = s.encode("utf-8")
    if len(b) > 65535:
        raise MQTTError("string too long")
    return struct.pack("!H", len(b)) + b


def packet(ptype: int, flags: int, body: bytes) -> bytes:
    return bytes([(ptype << 4) | flags]) + encode_length(len(body)) + body


def connect_packet(client_id: str, keepalive: int, username: str | None, password: str | None, will: tuple[str, bytes, bool] | None) -> bytes:
    flags = 0x02  # clean session
    payload = _str(client_id)
    if will:
        topic, msg, retain = will
        flags |= 0x04 | (0x20 if retain else 0) | (0x08)  # will flag, will retain, will QoS 1
        payload += _str(topic) + struct.pack("!H", len(msg)) + msg
    if username:
        flags |= 0x80
        payload += _str(username)
        if password is not None:
            flags |= 0x40
            payload += _str(password)
    body = _str("MQTT") + bytes([4, flags]) + struct.pack("!H", keepalive) + payload
    return packet(CONNECT, 0, body)


def publish_packet(topic: str, payload: bytes, qos: int = 0, retain: bool = False, pid: int = 0) -> bytes:
    body = _str(topic) + (struct.pack("!H", pid) if qos else b"") + payload
    return packet(PUBLISH, (qos << 1) | (1 if retain else 0), body)


def subscribe_packet(pid: int, topic: str, qos: int = 0) -> bytes:
    return packet(SUBSCRIBE, 0x02, struct.pack("!H", pid) + _str(topic) + bytes([qos]))


class MQTTClient:
    """Thread-safe publisher with automatic reconnect."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str | None = None,
        password: str | None = None,
        client_id: str = "bifrost",
        will: tuple[str, bytes, bool] | None = None,
        keepalive: int = 30,
        on_connect: Callable[[], None] | None = None,
        on_message: Callable[[str, bytes], None] | None = None,
        timeout: float = 10,
    ) -> None:
        self.host, self.port, self.username, self.password = host, int(port), username, password
        self.client_id, self.will, self.keepalive, self.timeout = client_id, will, keepalive, timeout
        self.on_connect, self.on_message = on_connect, on_message
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()  # one writer at a time
        self._pid = 0
        self._subs: list[str] = []
        self._stop = threading.Event()
        self._connected = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_error: str | None = None

    # --- state ---------------------------------------------------------------
    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    def _next_pid(self) -> int:
        self._pid = self._pid % 65535 + 1
        return self._pid

    # --- low level -------------------------------------------------------------
    def _recv_exact(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            sock = self._sock
            if sock is None:
                raise MQTTError("not connected")
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise MQTTError("connection closed")
            buf += chunk
        return buf

    def _read_packet(self) -> tuple[int, int, bytes]:
        head = self._recv_exact(1)[0]
        mult, length = 1, 0
        for _ in range(4):
            b = self._recv_exact(1)[0]
            length += (b & 0x7F) * mult
            if not b & 0x80:
                break
            mult *= 128
        else:
            raise MQTTError("bad length")
        if length > MAX_PACKET:
            raise MQTTError("packet too large")
        return head >> 4, head & 0x0F, self._recv_exact(length) if length else b""

    def _send(self, data: bytes) -> None:
        with self._lock:
            if self._sock is None:
                raise MQTTError("not connected")
            self._sock.sendall(data)

    # --- public --------------------------------------------------------------
    def connect_once(self) -> None:
        """Open the connection and wait for CONNACK (raises MQTTError)."""
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        sock.settimeout(self.timeout)
        self._sock = sock
        try:
            sock.sendall(connect_packet(self.client_id, self.keepalive, self.username, self.password, self.will))
            ptype, _, body = self._read_packet()
            if ptype != CONNACK or len(body) < 2:
                raise MQTTError("no CONNACK")
            if body[1] != 0:
                raise MQTTError(f"broker refused the connection (code {body[1]})")
        except Exception:
            self._close()
            raise
        sock.settimeout(1.0)
        self._connected.set()
        self.last_error = None
        for t in self._subs:
            self._send(subscribe_packet(self._next_pid(), t))

    def publish(self, topic: str, payload: str | bytes, retain: bool = False, qos: int = 0) -> bool:
        """Publish; False when not connected (the caller keeps its fallback)."""
        if not self.connected:
            return False
        data = payload.encode("utf-8") if isinstance(payload, str) else payload
        try:
            self._send(publish_packet(topic, data, qos=qos, retain=retain, pid=self._next_pid() if qos else 0))
            return True
        except (OSError, MQTTError) as err:
            self._lost(err)
            return False

    def subscribe(self, topic: str) -> None:
        self._subs.append(topic)
        if self.connected:
            try:
                self._send(subscribe_packet(self._next_pid(), topic))
            except (OSError, MQTTError) as err:
                self._lost(err)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="bifrost-mqtt", daemon=True)
        self._thread.start()

    def stop(self, final: list[tuple[str, str, bool]] | None = None) -> None:
        """Publish the last messages (e.g. "offline"), disconnect cleanly and stop the thread."""
        self._stop.set()
        if self.connected:
            for topic, payload, retain in final or []:
                self.publish(topic, payload, retain=retain, qos=1)
            try:
                self._send(packet(DISCONNECT, 0, b""))
            except (OSError, MQTTError):
                pass
        self._close()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=3)

    # --- loop ----------------------------------------------------------------
    def _close(self) -> None:
        self._connected.clear()
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def _lost(self, err: object) -> None:
        if self.connected:
            LOG.warning("MQTT connection lost: %s", err)
        self.last_error = str(err)
        self._close()

    def _run(self) -> None:
        backoff = 2.0
        while not self._stop.is_set():
            if not self.connected:
                try:
                    self.connect_once()
                    LOG.info("MQTT connected to %s:%s", self.host, self.port)
                    backoff = 2.0
                    if self.on_connect:
                        self.on_connect()
                except Exception as err:  # noqa: BLE001 – keep retrying
                    self.last_error = str(err) or type(err).__name__
                    self._close()
                    self._stop.wait(backoff)
                    backoff = min(backoff * 2, 60.0)
                    continue
            last_ping = time.monotonic()
            while self.connected and not self._stop.is_set():
                try:
                    ptype, flags, body = self._read_packet()
                except TimeoutError:
                    ptype = None
                except (OSError, MQTTError) as err:
                    if not self._stop.is_set():
                        self._lost(err)
                    break
                if ptype == PUBLISH:
                    self._incoming(flags, body)
                if time.monotonic() - last_ping > self.keepalive / 2:
                    last_ping = time.monotonic()
                    try:
                        self._send(packet(PINGREQ, 0, b""))
                    except (OSError, MQTTError) as err:
                        self._lost(err)
                        break

    def _incoming(self, flags: int, body: bytes) -> None:
        tl = struct.unpack("!H", body[:2])[0]
        topic = body[2 : 2 + tl].decode("utf-8", "replace")
        rest = body[2 + tl :]
        qos = (flags >> 1) & 3
        if qos:
            pid, rest = struct.unpack("!H", rest[:2])[0], rest[2:]
            try:
                self._send(packet(PUBACK, 0, struct.pack("!H", pid)))
            except (OSError, MQTTError):
                pass
        if self.on_message:
            try:
                self.on_message(topic, rest)
            except Exception:  # noqa: BLE001 – a callback must not kill the loop
                LOG.exception("MQTT message handler failed")
