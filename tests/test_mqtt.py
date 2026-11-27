import json
import socket
import struct
import threading
import time

import pytest

from bifrost_app import mqtt
from bifrost_app.outlet import AVAIL, SAFETY, Outlet, discovery, kind_of


class FakeBroker:
    """Tiny MQTT 3.1.1 broker for one client: records CONNECT, PUBLISH, SUBSCRIBE, DISCONNECT."""

    def __init__(self, refuse=0):
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.refuse = refuse
        self.connect = None
        self.pubs = []  # (topic, payload, retain)
        self.subs = []
        self.disconnected = False
        self.conn = None
        threading.Thread(target=self._run, daemon=True).start()

    def _read(self, c):
        head = c.recv(1)
        if not head:
            return None
        mult, length = 1, 0
        while True:
            b = c.recv(1)[0]
            length += (b & 0x7F) * mult
            if not b & 0x80:
                break
            mult *= 128
        body = b""
        while len(body) < length:
            body += c.recv(length - len(body))
        return head[0] >> 4, head[0] & 15, body

    def _run(self):
        c, _ = self.srv.accept()
        self.conn = c
        while True:
            try:
                p = self._read(c)
            except OSError:
                return
            if p is None:
                return
            t, flags, body = p
            if t == mqtt.CONNECT:
                self.connect = body
                c.sendall(bytes([0x20, 2, 0, self.refuse]))
            elif t == mqtt.PUBLISH:
                tl = struct.unpack("!H", body[:2])[0]
                topic = body[2 : 2 + tl].decode()
                rest = body[2 + tl :]
                if (flags >> 1) & 3:
                    rest = rest[2:]
                self.pubs.append((topic, rest.decode(), bool(flags & 1)))
            elif t == mqtt.SUBSCRIBE:
                tl = struct.unpack("!H", body[2:4])[0]
                self.subs.append(body[4 : 4 + tl].decode())
                c.sendall(bytes([0x90, 3]) + body[:2] + b"\x00")
            elif t == mqtt.PINGREQ:
                c.sendall(bytes([0xD0, 0]))
            elif t == mqtt.DISCONNECT:
                self.disconnected = True
                return

    def send(self, topic, payload):
        self.conn.sendall(mqtt.publish_packet(topic, payload.encode()))


def wait(cond, t=3.0):
    end = time.time() + t
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_length_encoding():
    assert mqtt.encode_length(0) == b"\x00"
    assert mqtt.encode_length(127) == b"\x7f"
    assert mqtt.encode_length(128) == b"\x80\x01"
    assert mqtt.encode_length(16383) == b"\xff\x7f"
    with pytest.raises(mqtt.MQTTError):
        mqtt.encode_length(300_000_000)


def test_client_connects_with_will_publishes_and_receives():
    b = FakeBroker()
    got = []
    c = mqtt.MQTTClient("127.0.0.1", b.port, "user", "pw", will=(AVAIL, b"offline", True), on_message=lambda t, p: got.append((t, p)))
    c.subscribe("homeassistant/status")
    c.start()
    assert wait(lambda: c.connected)
    assert b"bifrost/status" in b.connect and b"offline" in b.connect and b"user" in b.connect and b"pw" in b.connect
    assert c.publish("a/b", "1", retain=True)
    assert wait(lambda: ("a/b", "1", True) in b.pubs)
    assert wait(lambda: "homeassistant/status" in b.subs)
    b.send("homeassistant/status", "online")
    assert wait(lambda: got == [("homeassistant/status", b"online")])
    c.stop(final=[(AVAIL, "offline", True)])
    assert wait(lambda: b.disconnected)
    assert (AVAIL, "offline", True) in b.pubs


def test_refused_connection_is_an_error():
    b = FakeBroker(refuse=5)
    c = mqtt.MQTTClient("127.0.0.1", b.port, "u", "bad")
    with pytest.raises(mqtt.MQTTError):
        c.connect_once()
    assert not c.connected and not c.publish("x", "y")


class Store:
    def __init__(self):
        self.v = {}

    def get_value(self, k):
        return self.v.get(k)

    def set_value(self, k, v):
        self.v[k] = v


class Rest:
    def __init__(self, states=(), registry=()):
        self.written, self.deleted = [], []
        self.states, self.registry = list(states), list(registry)

    def set_state(self, eid, state, attrs):
        self.written.append((eid, state))

    def delete_state(self, eid):
        self.deleted.append(eid)

    def get_states(self):
        return [{"entity_id": e} for e in self.states]

    def registries(self):
        return {"entities": [{"entity_id": e} for e in self.registry]}


def test_discovery_payload():
    topic, cfg = discovery("binary_sensor.bifrost_empty_confirmed", {"friendly_name": "Bifrost house empty confirmed", "icon": "mdi:shield-home"}, "0.12.0", 90)
    assert topic == "homeassistant/binary_sensor/bifrost/bifrost_empty_confirmed/config"
    assert cfg["unique_id"] == "bifrost_empty_confirmed_binary_sensor" and cfg["default_entity_id"] == "binary_sensor.bifrost_empty_confirmed"
    assert cfg["availability_topic"] == AVAIL and cfg["expire_after"] == 90 and cfg["device"]["identifiers"] == ["bifrost"]
    assert cfg["name"] == "House empty confirmed" and cfg["payload_on"] == "on"
    assert kind_of("sensor.bifrost_person_alex") == "people" and kind_of("sensor.bifrost_p_home") == "status" and kind_of("binary_sensor.bifrost_zone_sofa") == "zones"


def test_rest_fallback_fails_closed_and_adds_freshness():
    rest = Rest()
    out = Outlet(rest, Store(), interval=30)
    out.fail_safe("Bifrost started")
    assert ("binary_sensor.bifrost_empty_confirmed", "off") in rest.written and ("binary_sensor.bifrost_house_empty", "off") in rest.written
    rest.written.clear()
    out.set_state("binary_sensor.bifrost_empty_confirmed", "on", {})
    assert rest.written == []  # held off until a good evaluation
    out.ok()
    out.set_state("binary_sensor.bifrost_empty_confirmed", "on", {})
    assert rest.written == [("binary_sensor.bifrost_empty_confirmed", "on")]
    attrs = out.entities["binary_sensor.bifrost_empty_confirmed"]["attrs"]
    assert attrs["valid_until"] > attrs["updated_at"]


def test_mqtt_outlet_safety_order_discovery_switching_and_cleanup():
    b = FakeBroker()
    rest = Rest(states=["sensor.bifrost_home_status", "binary_sensor.bifrost_old_pattern", "sensor.kitchen"], registry=[])
    store = Store()
    out = Outlet(rest, store, interval=30, version="0.12.0")
    m = mqtt.MQTTClient("127.0.0.1", b.port, will=(AVAIL, b"offline", True))
    out.attach_mqtt(m, "core-mosquitto:1883")
    out.set_state("binary_sensor.bifrost_empty_confirmed", "on", {"friendly_name": "Bifrost house empty confirmed"})
    m.start()
    assert wait(lambda: (AVAIL, "online", True) in b.pubs)
    topics = [p[0] for p in b.pubs]
    # safety off comes before "online"
    assert topics.index("bifrost/binary_sensor/bifrost_empty_confirmed/state") < topics.index(AVAIL)
    assert b.pubs[topics.index("bifrost/binary_sensor/bifrost_empty_confirmed/state")][1] == "off"
    assert any(t.startswith("homeassistant/binary_sensor/bifrost/") for t in topics)
    # old REST states removed once, registry entities and foreign states untouched
    assert sorted(rest.deleted) == ["binary_sensor.bifrost_old_pattern", "sensor.bifrost_home_status"] and store.get_value("mqtt_migrated")
    assert out.mode == "mqtt"
    out.ok()
    out.set_state("sensor.bifrost_home_status", "home", {"friendly_name": "Bifrost home status"})
    assert wait(lambda: ("bifrost/sensor/bifrost_home_status/state", "home", True) in b.pubs)
    assert all(e != "sensor.bifrost_home_status" for e, _ in rest.written)  # with a broker nothing goes via REST
    # switching off removes the discovery config; safety needs a confirmation and writes off first
    out.set_enabled("sensor.bifrost_home_status", False)
    assert wait(lambda: ("homeassistant/sensor/bifrost/bifrost_home_status/config", "", True) in b.pubs)
    with pytest.raises(ValueError):
        out.set_enabled("binary_sensor.bifrost_empty_confirmed", False)
    with pytest.raises(ValueError):
        out.set_enabled("light.kitchen", False)
    n = len(b.pubs)
    out.set_state("sensor.bifrost_home_status", "away", {})
    time.sleep(0.1)
    assert all(p[0] != "bifrost/sensor/bifrost_home_status/state" for p in b.pubs[n:])  # off = not published
    assert json.loads(store.get_value("entities_off")) == ["sensor.bifrost_home_status"]
    v = out.view()
    assert v["mode"] == "mqtt" and any(r["entity_id"] == "sensor.bifrost_home_status" and not r["on"] for r in v["entities"])
    # stop: safety off, then offline, then a clean disconnect
    out.stop()
    assert wait(lambda: b.disconnected)
    last = [p for p in b.pubs if p[0] in (AVAIL, "bifrost/binary_sensor/bifrost_empty_confirmed/state")][-2:]
    assert last == [("bifrost/binary_sensor/bifrost_empty_confirmed/state", "off", True), (AVAIL, "offline", True)]


def test_service_fails_closed_on_start_and_error(tmp_path, monkeypatch):
    from demo import build

    svc = build(str(tmp_path / "h.db"))
    svc.start_outlet()  # demo: no broker → REST
    for eid in SAFETY:
        assert svc.client.published[eid][0] == "off"
    svc.evaluate()
    assert not svc.out.failed_safe
    svc.out.fail_safe("error in the evaluation")
    assert svc.client.published["binary_sensor.bifrost_empty_confirmed"][0] == "off"
    view = svc.own_entities_view()
    assert view["mode"] == "rest" and any(r["entity_id"] == "binary_sensor.bifrost_empty_confirmed" and r["safety"] for r in view["entities"])
    with pytest.raises(ValueError):
        svc.set_own_entity({"entity_id": "sensor.bifrost_reason"})
    svc.set_own_entity({"entity_id": "sensor.bifrost_reason", "on": False})
    assert "sensor.bifrost_reason" in svc.client.deleted


def test_own_entities_are_never_an_input(tmp_path):
    from demo import build

    svc = build(str(tmp_path / "h.db"))
    svc.client.states.append(
        {"entity_id": "binary_sensor.bifrost_sofa", "state": "on", "last_changed": "2026-01-01T00:00:00+00:00", "attributes": {"friendly_name": "Bifrost Sofa", "device_class": "occupancy"}}
    )
    svc.scan()
    assert "binary_sensor.bifrost_sofa" not in svc.snap.entities
