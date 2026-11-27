from datetime import datetime, timedelta

from sim import household

from bifrost_app.patterns import outcomes_from_decisions
from bifrost_app.routines import mine, progress


def plans():
    s = household(28)
    outs = outcomes_from_decisions(s.decisions, lambda v: datetime.fromisoformat(v))
    return mine(s.events, outs, owners={"device_tracker.phone_a:home": "Person A", "device_tracker.phone_a:away": "Person A"}), s


def test_departure_plan_has_then_steps_companion_and_quiet():
    ps, _ = plans()
    dep = [p for p in ps if p["goal"] == "departure"]
    assert dep, "a departure routine should be found"
    p = dep[0]
    assert p["seen"] >= 5 and p["precision"] >= 0.85
    kinds = [s["kind"] for s in p["steps"]]
    assert "step" in kinds or "and" in kinds
    assert any("span" in s for s in p["steps"][1:])
    assert p["not"] and p["not"]["what"] == "motion"
    assert p["conditions"]["weekdays"] and ":" in p["conditions"]["time"]["typical"]


def test_arrival_plan_and_who():
    ps, _ = plans()
    arr = [p for p in ps if p["goal"] == "arrival"]
    assert arr
    assert any(c["token"].startswith("device_tracker.") for p in arr for c in p["companions"]) or any(x.startswith("device_tracker.") for p in arr for s in p["steps"] for x in s["tokens"])


def test_progress_for_early_detection():
    ps, s = plans()
    p = next(p for p in ps if p["goal"] == "departure")
    core = [st for st in p["steps"] if st["kind"] in ("step", "and", "or")]
    now = s.t + timedelta(days=1)
    recent = [(now - timedelta(minutes=5), core[0]["tokens"][0])]
    assert 0 < progress(p, recent, now) < 1
    assert progress(p, [], now) == 0


def test_no_plans_without_data():
    assert mine([], []) == []
