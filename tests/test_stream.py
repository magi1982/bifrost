import threading
from datetime import UTC, datetime, timedelta

from test_service import FakeClient

from bifrost_app.ha_client import parse_state_changed
from bifrost_app.service import BifrostService
from bifrost_app.store import Store

T0 = datetime(2026, 1, 5, 17, 30, tzinfo=UTC)


def msg(eid, state, ts):
    return {"type": "event", "event": {"event_type": "state_changed", "data": {"entity_id": eid, "new_state": {"state": state, "last_changed": ts}}}}


def test_parse_state_changed_reads_exact_time():
    eid, state, ts = parse_state_changed(msg("binary_sensor.door", "on", "2026-01-05T17:30:04.250+00:00"))
    assert eid == "binary_sensor.door" and state == "on"
    assert ts == T0 + timedelta(seconds=4.25)


def test_parse_state_changed_ignores_other_messages_and_removed_entities():
    assert parse_state_changed({"type": "result", "id": 1, "success": True}) is None
    removed = {"type": "event", "event": {"data": {"entity_id": "light.x", "new_state": None}, "time_fired": "2026-01-05T17:30:00+00:00"}}
    eid, state, ts = parse_state_changed(removed)
    assert eid == "light.x" and state is None and ts == T0


def make(tmp_path, **opts):
    client = FakeClient()
    svc = BifrostService(client, Store(str(tmp_path / "s.db")), {"shadow_mode": True, **opts})
    svc.scan()
    svc.snap.entities["binary_sensor.hall_motion"].status = "included"
    return svc, client


def test_stream_records_exact_edges_only_for_used_signals(tmp_path):
    svc, _ = make(tmp_path)
    svc._seed_edges()  # current state "off" becomes the baseline
    svc.on_state_changed("binary_sensor.hall_motion", "on", T0)
    svc.on_state_changed("binary_sensor.hall_motion", "on", T0 + timedelta(seconds=3))  # no change
    svc.on_state_changed("binary_sensor.hall_motion", "off", T0 + timedelta(seconds=40))
    svc.on_state_changed("update.core", "on", T0)  # not used → ignored
    ev = svc.store.events_since(T0 - timedelta(minutes=1))
    assert [(e["entity_id"], e["kind"]) for e in reversed(ev)] == [("binary_sensor.hall_motion", "on"), ("binary_sensor.hall_motion", "off")]
    assert ev[-1]["ts"].startswith("2026-01-05T17:30:00")
    view = svc.status_view()["stream"]
    assert view["connected"] and view["events"] == 2 and view["duplicates"] == []


def test_stream_can_be_switched_off(tmp_path):
    svc, _ = make(tmp_path, event_stream=False)
    assert svc.start_stream() is None


def test_stream_loop_reconnects_and_stops(tmp_path):
    svc, client = make(tmp_path)
    calls = []

    def fake_stream(on_change, stop, on_connected=None):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("connection refused")
        on_connected()
        on_change("binary_sensor.hall_motion", "on", T0)
        stop.set()

    client.stream_state_changes = fake_stream
    svc._stop.wait = lambda t: None  # no real waiting in tests
    t = threading.Thread(target=svc._stream_loop)
    t.start()
    t.join(timeout=5)
    assert len(calls) == 2
    assert svc.stream["events"] == 1 and not svc.stream["connected"]


def test_without_stream_the_poll_loop_still_records_events(tmp_path):
    svc, client = make(tmp_path)
    svc.evaluate()
    client.states[1] = {**client.states[1], "state": "on"}
    svc.evaluate()
    kinds = [e["kind"] for e in svc.store.events_since(datetime.now(UTC) - timedelta(minutes=1))]
    assert kinds == ["on"]  # recorded by the poll loop as an edge


def _ws_pair():
    import socket

    from bifrost_app.ha_client import _SimpleWebSocket

    a, b = socket.socketpair()
    ws = object.__new__(_SimpleWebSocket)
    ws.sock, ws._buf, ws._in_frame = a, b"", False
    a.settimeout(0.05)
    return ws, b


def test_idle_timeout_is_safe_but_a_stalled_message_reconnects():
    import json

    import pytest

    from bifrost_app.ha_client import HAError

    ws, server = _ws_pair()
    with pytest.raises(TimeoutError):
        ws.recv_json()  # nothing sent yet: plain idle timeout, safe to ping and continue
    payload = json.dumps({"type": "pong"}).encode()
    server.sendall(bytes([0x81, len(payload)]) + payload)
    assert ws.recv_json() == {"type": "pong"}
    server.sendall(bytes([0x81, 50]) + b"half")  # header + part of the payload, then silence
    with pytest.raises(HAError):
        ws.recv_json()
