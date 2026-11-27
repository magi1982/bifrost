from datetime import timedelta

from sim import META, SIDES, household

from bifrost_app import evidence, hindsight, value
from bifrost_app.optimize import suggestions


def judged():
    s = household(21)
    events = list(s.events)
    meta = {k: dict(v) for k, v in META.items()}
    meta["binary_sensor.zone_ground_floor"] = {"category": "motion"}  # a summary zone from another system
    meta["binary_sensor.motion_hallway_copy"] = {"category": "motion"}
    for e in s.events:
        if e["entity_id"] == "binary_sensor.motion_living" and e["kind"] == "on":
            t = __import__("datetime").datetime.fromisoformat(e["ts"])
            events.append({"ts": (t + timedelta(seconds=20)).isoformat(), "entity_id": "binary_sensor.zone_ground_floor", "kind": "on", "state": "on"})
            events.append({"ts": (t + timedelta(minutes=25)).isoformat(), "entity_id": "binary_sensor.zone_ground_floor", "kind": "off", "state": "off"})
    hind = hindsight.label(events, meta, SIDES)
    ev = evidence.learn(events, hind, meta)
    dups = [{"a": "binary_sensor.motion_hallway", "b": "binary_sensor.motion_hallway_copy", "together": 50, "ratio": 0.99}]
    doctor = [{"entity_id": "binary_sensor.motion_dead", "problem": "dead"}]
    return value.judge(events, meta, ev, doctor, dups, days=21)


def test_verdicts_per_signal():
    v = judged()
    assert v["binary_sensor.zone_ground_floor"]["verdict"] == value.SLOW and v["binary_sensor.zone_ground_floor"]["hold_s"] >= value.SLOW_HOLD
    assert v["binary_sensor.motion_dead"]["verdict"] == value.NOTHING and v["binary_sensor.motion_dead"]["reason"] == "dead"
    assert v["binary_sensor.motion_hallway_copy"]["reason"] == "duplicate"
    assert v["binary_sensor.motion_living"]["verdict"] == value.VALUABLE
    assert sum(value.counts(v).values()) == len(v)


def test_useless_signals_are_only_suggested_to_switch_off():
    v = judged()
    ents = [{"entity_id": "binary_sensor.zone_ground_floor", "name": "Zone", "domain": "binary_sensor", "device_class": "occupancy", "status": "included", "category": "motion"}]
    out = suggestions(ents, values=v)
    assert out and out[0]["key"] == "value_slow" and out[0]["suggest"]["status"] == "ignored"
