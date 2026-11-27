from datetime import timedelta

from sim import META, household

from bifrost_app import blocks
from bifrost_app.blocks import Detector, capability, learn, sensor_doctor


def model():
    s = household(21)
    return learn(s.events, META, s.decisions), s


def test_neighbours_and_walking_times():
    m, _ = model()
    pairs = {(n["a"], n["b"]): n for n in m["neighbours"]}
    hl = pairs[("binary_sensor.motion_hallway", "binary_sensor.motion_living")]
    assert hl["count"] >= 5 and 2 <= hl["walk"]["typical"] <= 10


def test_inside_and_outside_sensors_are_found_without_names():
    s = household(21)
    plain = {eid: {**v, "name": eid.split(".")[1][:3], "area": None} for eid, v in META.items()}  # no helpful names
    m = learn(s.events, plain, s.decisions)
    sides = {k: v["side"] for k, v in m["sides"].items()}
    assert sides["binary_sensor.motion_outside_front"] == "outside"
    assert sides["binary_sensor.motion_outside_garage"] == "outside"
    assert sides["binary_sensor.motion_cloakroom"] == "inside"


def test_entrances_with_direction_and_door_roles():
    m, _ = model()
    ens = {e["door"]: e for e in m["entrances"]}
    assert ens["binary_sensor.garage_door"]["inside"] == "binary_sensor.motion_cloakroom"
    assert ens["binary_sensor.garage_door"]["outside"] == "binary_sensor.motion_outside_garage"
    assert ens["binary_sensor.front_door"]["inside"] == "binary_sensor.motion_hallway"
    assert m["roles"]["binary_sensor.garage_door"]["role"] == "entrance"
    assert m["roles"]["binary_sensor.terrace_door"]["role"] == "inside_only"
    assert m["roles"]["binary_sensor.garage_door"]["entry"] > 0 and m["roles"]["binary_sensor.garage_door"]["exit"] > 0


def test_disturbances_and_map():
    m, _ = model()
    assert [d["sensor"] for d in m["disturbances"]] == ["binary_sensor.motion_hallway"]
    kinds = {link["kind"] for link in m["map"]["links"]}
    assert {"walk", "door_inside", "door_outside"} <= kinds


def test_sensor_doctor_finds_dead_and_never_home():
    m, s = model()
    probs = {(p["entity_id"], p["problem"]) for p in sensor_doctor(s.events, META, days=21, current={})}
    assert ("binary_sensor.motion_dead", "dead") in probs
    assert not any(p == "never_home" for _, p in probs)  # phones come home every day


def test_capability_check():
    m, _ = model()
    cap = capability(m, people_total=3, people_with_source=2)
    assert cap["doors_with_direction"] >= 2 and cap["outside_sensors"] == 2
    assert "people_sources" in cap["missing"] and "outside_motion" not in cap["missing"]


def test_detector_classifies_live_entry_and_exit():
    m, s = model()
    d = Detector()
    d.model = m
    t0 = s.t + timedelta(days=1)
    seq = [("binary_sensor.motion_outside_front", 0), ("binary_sensor.front_door", 10), ("binary_sensor.motion_hallway", 13)]
    for eid, sec in seq:
        d.feed({"ts": (t0 + timedelta(seconds=sec)).isoformat(), "entity_id": eid, "kind": "on"})
    assert d.tick(t0 + timedelta(seconds=20)) == []  # still waiting for the after-window
    out = d.tick(t0 + timedelta(seconds=120))
    assert out and out[0]["result"] == "entry" and out[0]["door"] == "binary_sensor.front_door"
    t1 = t0 + timedelta(hours=2)
    for eid, sec in [("binary_sensor.motion_cloakroom", 0), ("binary_sensor.garage_door", 8), ("binary_sensor.motion_outside_garage", 12)]:
        d.feed({"ts": (t1 + timedelta(seconds=sec)).isoformat(), "entity_id": eid, "kind": "on"})
    assert d.tick(t1 + timedelta(seconds=120)) == []  # exit needs the silence
    out = d.tick(t1 + timedelta(seconds=blocks.EXIT_SILENCE + 30))
    assert out[0]["result"] == "exit"


def test_min_people_from_fast_far_apart_sensors():
    m, s = model()
    d = Detector()
    d.model = m
    t = s.t + timedelta(days=2)
    d.feed({"ts": t.isoformat(), "entity_id": "binary_sensor.motion_upstairs", "kind": "on"})
    d.feed({"ts": (t + timedelta(seconds=1)).isoformat(), "entity_id": "binary_sensor.motion_cloakroom", "kind": "on"})
    assert d.people_inside_min(t + timedelta(seconds=5)) == 2


def test_quiet_after_a_door_is_no_exit_without_confirmation():
    m, s = model()
    d = Detector()
    d.model = m
    t1 = s.t + timedelta(days=2)
    # inside, door, then silence – but nothing outside: somebody may just sit in a room without a sensor
    for eid, sec in [("binary_sensor.motion_cloakroom", 0), ("binary_sensor.garage_door", 8)]:
        d.feed({"ts": (t1 + timedelta(seconds=sec)).isoformat(), "entity_id": eid, "kind": "on"})
    out = d.tick(t1 + timedelta(seconds=blocks.EXIT_SILENCE + 30))
    assert out[0]["result"] == blocks.DOOR_USED
