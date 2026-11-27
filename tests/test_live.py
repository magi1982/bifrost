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
    lane = v["lane"]["events"]
    assert any(x.get("lane") == "Kitchen" and x["entity_id"] == "light.kitchen" for x in lane)
    assert any(x["kind"] == "auto" and x["entity_id"] == "light.garden" for x in lane)
    assert sig["sensor.bath_humidity"]["event"] == "humidity_jump"
    assert sig["vacuum.robot"]["noise"]
    assert [p["entity_id"] for p in v["last_path"]][:2] == ["binary_sensor.motion_outside_garage", "binary_sensor.garage_door"]
    kinds = {g["kind"] for g in v["gaps"]}
    assert {"door_no_direction", "signal_without_area"} <= kinds
    assert v["kpis"]["last"]["entity_id"] == "binary_sensor.motion_hallway"
    # timer-switched light never counts as a person
    assert "light.garden" in svc.live.automated(timedelta(hours=24), datetime.now(UTC))


def test_identity_entities_explain_entries_and_become_steps(tmp_path):
    from demo import build

    from bifrost_app.routines import token_of

    svc = build(str(tmp_path / "demo.db"))
    eid = "sensor.front_door_last_user"
    t = datetime.now(UTC)
    svc.brain.people.map_access("Family code", "household")
    svc.brain.identity.clear()
    svc.on_state_changed(eid, "Family code", t)
    svc.on_state_changed(eid, "", t + timedelta(seconds=3))
    svc.on_state_changed(eid, "Person B", t + timedelta(seconds=10))
    svc.on_state_changed(eid, "", t + timedelta(seconds=13))
    svc.on_state_changed(eid, "42", t + timedelta(seconds=20))  # a user number nobody assigned yet – still authorised
    svc.on_state_changed(eid, "", t + timedelta(seconds=23))
    svc.on_state_changed(eid, "Zugang verweigert", t + timedelta(seconds=30))
    who = [(i["who"], i["pid"]) for i in svc.brain.identity]
    assert ("household", None) in who and ("Person B", "person_b") in who and ("unknown", None) in who
    assert len(who) == 3  # the denial explains nothing
    assert any(d["key"] == f"access_denied:{eid}" for d in svc.brain.inbox.deviations())
    seen = {s["value"]: s["target"] for s in svc.sources_view()["identity"][0]["seen"]}
    assert seen["42"] == "" and seen["Family code"] == "household" and seen["Person B"] == "person_b"
    evs = [e for e in svc.store.events_since(t - timedelta(seconds=1)) if e["kind"] == "access"]
    toks = {token_of(e) for e in evs}
    assert f"access:{eid}:household" in toks and f"access:{eid}:person_b" in toks and None in toks  # denied → no token


def test_smart_lock_reports_who_unlocked(tmp_path):
    from demo import build

    svc = build(str(tmp_path / "demo2.db"))
    svc.client.states.append({"entity_id": "lock.front", "state": "locked", "last_changed": datetime.now(UTC).isoformat(), "attributes": {"friendly_name": "Front lock"}})
    svc.scan()
    svc.update_entity("lock.front", "included", "security", "Evidence")
    svc.brain.identity.clear()
    t = datetime.now(UTC)
    svc.on_state_changed("lock.front", "unlocked", t, attrs={"changed_by": "Person B"})
    svc.on_state_changed("lock.front", "locked", t + timedelta(seconds=30), attrs={"changed_by": "Person B"})
    assert [(i["who"], i["pid"]) for i in svc.brain.identity] == [("Person B", "person_b")]
    assert "lock.front" in [x["entity_id"] for x in svc.sources_view()["identity"]]


def test_corrections_teach_something(tmp_path):
    from demo import build

    svc = build(str(tmp_path / "corr.db"))
    now = datetime.now(UTC)
    b = svc.brain
    # whole house: Bifrost said away, somebody was home → wrong "empty" in the balance
    r = b.correct("away", "home", now)
    assert "balance:wrong_empty" in r["learned"]
    # culprit: the hallway motion was the cat while nobody was home → counts less on the scale, disturbance question
    r = b.correct("home", "away", now, culprit="binary_sensor.motion_hallway")
    assert "trust:binary_sensor.motion_hallway" in r["learned"]
    assert svc.store.get_obj("stats", "culprits")["binary_sensor.motion_hallway"] == 1
    assert any(q["type"] == "disturbance" for q in b.inbox.all())
    # person: phone said home three times, person was away → that phone only counts as weak
    for _ in range(3):
        b.correct("home", "away", now, person="person_a", person_said="home")
    assert b.strength("device_tracker.phone_a") == "weak"
    k = b.balance_view(now, 100, 0)["kpis"]
    assert k["wrong_empty"] >= 1 and k["wrong_home"] >= 1
    import pytest

    with pytest.raises(ValueError):
        b.correct("home", "away", now, culprit="light.not_used")
    with pytest.raises(ValueError):
        b.correct("home", "away", now, person="nobody")
