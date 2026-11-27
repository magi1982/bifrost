from datetime import UTC, datetime, timedelta

import pytest

from bifrost_app.engine import AWAY, HOME, Decision, Settings, Signal, decide
from bifrost_app.learning import Learner, is_unreliable, trust_score
from bifrost_app.store import Store

T0 = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "l.db"))
    yield s
    s.close()


def sig(eid, cat, role, state, t=T0):
    return Signal(eid, eid, cat, role, state, t)


def run(learner, state, conf, steps, sigs_fn, start=T0):
    t = start
    for i in range(steps):
        learner.observe(sigs_fn(i), Decision(state, conf, []), t)
        t += timedelta(minutes=5)
    return t


def test_score_and_threshold():
    assert trust_score(0, 0) == 0.5
    assert is_unreliable((0, 5)) and not is_unreliable((0, 4)) and not is_unreliable((5, 0)) and not is_unreliable(None)


def test_sensor_firing_while_away_loses_trust(store):
    lr = Learner(store)
    # pet-flap motion toggles while the house is confirmed empty
    run(lr, AWAY, 90, 8, lambda i: [sig("person.a", "devices", "Evidence", "not_home"), sig("binary_sensor.pet", "motion", "Evidence", "on" if i % 2 else "off")])
    a, d = store.get_trust()["binary_sensor.pet"]
    assert (a, d) == (0, 1)
    assert store.get_trust()["person.a"] == (1, 0)


def test_quiet_sensor_while_away_gains_trust(store):
    lr = Learner(store)
    run(lr, AWAY, 90, 8, lambda i: [sig("binary_sensor.hall", "motion", "Evidence", "off")])
    assert store.get_trust()["binary_sensor.hall"] == (1, 0)


def test_no_learning_without_confirmation(store):
    lr = Learner(store)
    run(lr, AWAY, 70, 10, lambda i: [sig("binary_sensor.hall", "motion", "Evidence", "on" if i % 2 else "off")])  # low confidence
    run(lr, HOME, 95, 3, lambda i: [sig("binary_sensor.hall", "motion", "Evidence", "on" if i % 2 else "off")], T0 + timedelta(hours=2))  # too short
    assert store.get_trust() == {}


def test_events_are_recorded(store):
    lr = Learner(store)
    run(lr, HOME, 90, 3, lambda i: [sig("binary_sensor.door", "openings", "Trigger", "on" if i == 1 else "off")])
    ev = store.events_since(T0 - timedelta(hours=1))
    assert [e["state"] for e in reversed(ev)] == ["on", "off"]


def test_engine_ignores_unreliable_activity():
    s = Settings()
    now = T0 + timedelta(hours=3)
    sigs = [
        Signal("person.a", "A", "devices", "Evidence", "not_home", T0),
        Signal("binary_sensor.pet", "Pet", "motion", "Evidence", "on", now),
        Signal("binary_sensor.door", "Door", "openings", "Evidence", "off", T0),
    ]
    assert decide(sigs, s, now).state == HOME
    d = decide(sigs, s, now, {"binary_sensor.pet"})
    assert d.state != HOME and d.ignored_unreliable == ["Pet"]
    s.use_learning = False
    assert decide(sigs, s, now, {"binary_sensor.pet"}).state == HOME


def test_guest_mode_and_anomaly():
    now = T0 + timedelta(hours=3)
    sigs = [Signal("person.a", "A", "devices", "Evidence", "not_home", T0), Signal("binary_sensor.hall", "Hall", "motion", "Evidence", "on", now)]
    d = decide(sigs, Settings(), now)
    assert d.state == HOME and d.anomaly
    assert decide([], Settings(guest_mode=True), now).state == HOME
