"""Live view building blocks: origin, learned timers, numeric events, last path."""

from datetime import UTC, datetime, timedelta

from bifrost_app.engine import Settings, Signal, decide
from bifrost_app.live import APP, AUTOMATION, PERSON, SCHEDULED, SENSOR, LiveBoard, NumericEvents, OriginLearner, classify_origin, origin_of

T0 = datetime(2026, 1, 5, 17, 0, tzinfo=UTC)


def _msg(ctx):
    return {"type": "event", "event": {"data": {"entity_id": "light.x", "new_state": {"state": "on", "context": ctx}}}}


def test_origin_from_context():
    assert origin_of(_msg({"id": "1", "parent_id": "a", "user_id": None})) == AUTOMATION
    assert origin_of(_msg({"id": "1", "parent_id": None, "user_id": "u"})) == APP
    assert origin_of(_msg({"id": "1"})) == "device"
    assert origin_of({"type": "event", "event": {"data": {}}}) == "device"


def test_classify_origin_by_category():
    assert classify_origin("device", "motion", False) == SENSOR
    assert classify_origin("automation", "manual", False) == AUTOMATION
    assert classify_origin("app", "manual", False) == APP
    assert classify_origin("device", "manual", False) == PERSON
    assert classify_origin("device", "manual", True) == SCHEDULED


def test_timer_is_learned_after_five_days():
    ol = OriginLearner()
    for day in range(1, 7):
        ol.record("light.garden", T0 - timedelta(days=day) + timedelta(minutes=day % 3))
    assert ol.scheduled("light.garden", T0)
    assert not ol.scheduled("light.garden", T0 + timedelta(hours=3))
    fresh = OriginLearner()
    fresh.load(ol.dump())
    assert fresh.scheduled("light.garden", T0)


def test_timer_needs_enough_days():
    ol = OriginLearner()
    for day in range(1, 4):
        ol.record("light.garden", T0 - timedelta(days=day))
    assert not ol.scheduled("light.garden", T0)


def test_humidity_jump_and_cooldown():
    ne = NumericEvents()
    assert ne.feed("sensor.bath_h", "55", T0, "humidity", "%") is None
    assert ne.feed("sensor.bath_h", "58", T0 + timedelta(minutes=2), "humidity", "%") is None
    assert ne.feed("sensor.bath_h", "66", T0 + timedelta(minutes=4), "humidity", "%") == "humidity_jump"
    assert ne.feed("sensor.bath_h", "75", T0 + timedelta(minutes=6), "humidity", "%") is None  # cooldown
    assert ne.trend("sensor.bath_h")["dir"] == "up"


def test_power_spike_in_kw_and_unknown_values():
    ne = NumericEvents()
    ne.feed("sensor.oven", "0.05", T0, "power", "kW")
    assert ne.feed("sensor.oven", "2.1", T0 + timedelta(minutes=1), "power", "kW") == "power_spike"
    assert ne.feed("sensor.temp", "21", T0, "temperature", "°C") is None
    assert ne.feed("sensor.bath_h", "n/a", T0, "humidity", "%") is None


def test_last_path_skips_automations_and_old_bursts():
    lb = LiveBoard()
    lb.note("binary_sensor.out", T0, "on", SENSOR)
    lb.note("light.garden", T0 + timedelta(seconds=5), "on", AUTOMATION)
    lb.note("binary_sensor.door", T0 + timedelta(seconds=15), "on", SENSOR)
    lb.note("binary_sensor.door", T0 + timedelta(seconds=20), "off", SENSOR)
    lb.note("binary_sensor.hall", T0 + timedelta(seconds=25), "on", SENSOR)
    path = lb.last_path(T0 + timedelta(seconds=30))
    assert [p["entity_id"] for p in path] == ["binary_sensor.out", "binary_sensor.door", "binary_sensor.hall"]
    assert lb.last_path(T0 + timedelta(hours=1)) == []
    assert lb.automated(timedelta(hours=1), T0 + timedelta(minutes=1)) == {"light.garden"}


def test_automated_light_is_not_activity():
    s = Settings(10, 15)
    sigs = [
        Signal("device_tracker.a", "Phone", "devices", "Evidence", "not_home", T0 - timedelta(hours=2)),
        Signal("light.garden", "Garden light", "manual", "Evidence", "on", T0 - timedelta(minutes=1)),
        Signal("binary_sensor.m", "Motion", "motion", "Evidence", "off", T0 - timedelta(hours=1)),
    ]
    assert decide(sigs, s, T0).state != "away"
    d = decide(sigs, s, T0, automated={"light.garden"})
    assert d.state == "away"
    assert any("Garden light" in r and "automation" in r for r in d.reasons)


def test_live_view_on_demo_household(tmp_path):
    from demo import build

    svc = build(str(tmp_path / "demo.db"))
    v = svc.live_view()
    floors = [f["name"] for f in v["floors"]]
    assert floors == ["Outside", "Ground floor", "Upper floor"]
    sig = {x["entity_id"]: x for f in v["floors"] for a in f["areas"] for x in a["signals"]}
    assert sig["light.garden"]["origin"] == AUTOMATION and not sig["light.garden"]["active"]
    assert sig["light.kitchen"]["origin"] == PERSON and sig["light.kitchen"]["active"]
    assert sig["sensor.bath_humidity"]["event"] == "humidity_jump"
    assert sig["vacuum.robot"]["noise"]
    assert [p["entity_id"] for p in v["last_path"]][:2] == ["binary_sensor.motion_outside_garage", "binary_sensor.garage_door"]
    kinds = {g["kind"] for g in v["gaps"]}
    assert {"door_no_direction", "signal_without_area"} <= kinds
    assert v["kpis"]["last"]["entity_id"] == "binary_sensor.motion_hallway"
    # timer-switched light never counts as a person
    assert "light.garden" in svc.live.automated(timedelta(hours=24), datetime.now(UTC))


def test_shared_household_code_explains_an_entry(tmp_path):
    from demo import build

    svc = build(str(tmp_path / "demo.db"))
    svc.brain.people.set_shared_access(["Family code"])
    t = datetime.now(UTC)
    svc.brain.on_edge({"ts": t, "entity_id": "sensor.front_door_last_user", "kind": "change", "state": "Family code"})
    assert any(i["who"] == "household" and i["strength"] == "strong" for i in svc.brain.identity)
