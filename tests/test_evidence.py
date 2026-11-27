from datetime import datetime, timedelta

from sim import META, SIDES, household

from bifrost_app import evidence as ev
from bifrost_app import hindsight as hs
from bifrost_app.brain import Brain, _sleep_window
from bifrost_app.engine import Decision
from bifrost_app.store import Store


def model(days=21, robot=False):
    s = household(days)
    events = list(s.events)
    meta = dict(META)
    if robot:
        meta["binary_sensor.robot_motion"] = {"category": "motion"}
        for seg in hs.label(events, meta, SIDES)["segments"]:
            if seg["label"] == hs.EMPTY:  # the robot runs while everybody is out
                t = seg["start"] + (seg["end"] - seg["start"]) / 2
                events += [{"ts": (t + timedelta(minutes=m)).isoformat(), "entity_id": "binary_sensor.robot_motion", "kind": "on", "state": "on"} for m in (0, 5)]
    # the owner confirmed the robot once as a disturbance: hindsight leaves it out, the scale still sees it fire
    hind = hs.label(events, meta, SIDES, exceptions={"binary_sensor.robot_motion"})
    return ev.learn(events, hind, meta), hind, s


def test_scale_is_learned_from_hindsight_and_explains_itself():
    m, hind, s = model()
    assert m["ready"] and m["samples"]["home"] > m["samples"]["empty"] > ev.MIN_SAMPLES
    w = m["weights"]
    assert w["binary_sensor.motion_living"]["active"] > 1 and w["device_tracker.phone_a"]["home"] > 1 > w["device_tracker.phone_a"]["away"]
    now = s.t
    home = ev.predict(m, {"binary_sensor.motion_living": now - timedelta(minutes=2)}, {"device_tracker.phone_a": "home", "device_tracker.phone_b": "home"}, now)
    away = ev.predict(m, {}, {"device_tracker.phone_a": "away", "device_tracker.phone_b": "away"}, now)
    assert home["p_home"] > 0.95 > 0.05 > away["p_home"]
    assert home["parts"][0]["entity_id"].startswith("device_tracker.")


def test_a_robot_that_runs_while_empty_is_not_counted():
    m, _, s = model(robot=True)
    assert "binary_sensor.robot_motion" in ev.unreliable(m)
    now = s.t
    p = ev.predict(m, {"binary_sensor.robot_motion": now}, {"device_tracker.phone_a": "away", "device_tracker.phone_b": "away"}, now)
    assert p["p_home"] < 0.05 and not p["parts"][0]["entity_id"].endswith("robot_motion")


def test_a_culprit_counts_less():
    m, _, s = model()
    now = s.t
    a = ev.predict(m, {"binary_sensor.motion_hallway": now}, {}, now)
    b = ev.predict(m, {"binary_sensor.motion_hallway": now}, {}, now, culprits={"binary_sensor.motion_hallway": 3})
    assert b["p_home"] < a["p_home"]


def test_split_states_and_calibration():
    assert sum(ev.split_states(0.73, 0.4).values()) == 100
    assert ev.split_states(0.0, 0.9) == {"home": 0, "asleep": 0, "away": 100}
    m, hind, s = model(7)
    seg = next(x for x in hind["segments"] if x["label"] == hs.EMPTY)
    preds = [(seg["start"] + timedelta(minutes=30), 0.95), (seg["start"] - timedelta(hours=1), 0.05)]
    cal = ev.calibration(preds, hind)
    assert cal[-1]["n"] == 1 and cal[-1]["share"] == 1.0


def test_brain_scale_only_makes_bifrost_more_careful(tmp_path):
    b = Brain(Store(str(tmp_path / "s.db")), {})
    b.evidence, _, _ = model(14)
    away = Decision("away", 95, ["Everybody away"], 100)
    prob = {"source": "evidence", "home": 40, "asleep": 0, "away": 60}
    d = b._apply_evidence(away, prob)
    assert d.state == "unknown" and "not sure" in d.reasons[0]
    assert b._apply_evidence(away, {**prob, "home": 8, "away": 92}).confidence == 92
    home = Decision("home", 80, [], 100)
    assert b._apply_evidence(home, {**prob, "home": 1, "away": 99}).state == "home"  # never turns into "empty"


def test_rules_fallback_and_sleep_window(tmp_path):
    b = Brain(Store(str(tmp_path / "s.db")), {})
    now = datetime.fromisoformat("2026-03-02T12:00:00+00:00")
    p = b.probabilities(Decision("away", 90, [], 100), {}, now)
    assert p["source"] == "rules" and p["away"] == 90 and sum(p[k] for k in ("home", "asleep", "away")) == 100
    beds = [datetime.fromisoformat(f"2026-03-0{d}T23:00:00").astimezone() for d in range(1, 6)]
    w = _sleep_window(beds)
    assert w["to"] == (w["from"] + 480) % 1440
