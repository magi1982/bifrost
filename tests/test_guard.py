from datetime import UTC, datetime, timedelta

from bifrost_app import guard
from bifrost_app.engine import Decision
from bifrost_app.guard import GuardState, apply, explain_entry, on_opening, tick

T = datetime(2026, 1, 5, 3, 0, tzinfo=UTC)


def away(conf=95):
    return Decision("away", conf, ["Everybody away"], 100)


def test_entry_explained_by_phone_and_weak_explanation_not_enough_at_night():
    ids = [{"ts": T + timedelta(seconds=40), "who": "Person A", "kind": "home", "strength": "weak"}]
    assert explain_entry(T, ids, False)["explained"]
    r = explain_entry(T, ids, False, night=True)
    assert not r["explained"] and r["too_weak"]
    assert explain_entry(T, ids + [{"ts": T, "who": "Person A", "kind": "nfc", "strength": "strong"}], False, night=True)["explained"]
    assert explain_entry(T, [], True)["by"] == "guest_mode"
    assert not explain_entry(T, [{"ts": T - timedelta(minutes=10), "who": "A", "kind": "home", "strength": "medium"}], False)["explained"]


def test_unexplained_entry_while_empty_is_a_suspicion_and_blocks_empty():
    gs = GuardState()
    s = on_opening(gs, {"door": "binary_sensor.front_door", "ts": T.isoformat(), "result": "entry"}, {"explained": False}, "away", T, level=2)
    assert s and s["level"] == 2 and gs.unknown_min == 1
    d, checks = apply(away(), {"all_away": True, "unclear": [], "home": []}, gs, T + timedelta(minutes=1), can_see_direction=True)
    assert d.state == "arriving" and "Entry detected" in d.reasons[0]
    d, checks = apply(away(), {"all_away": True, "unclear": [], "home": []}, gs, T + timedelta(minutes=30), can_see_direction=True)
    assert d.state == "unknown" and any("unknown person" in r for r in d.reasons)
    tick(gs, T + timedelta(minutes=30), None)
    assert gs.suspicion is None  # suspicion fades after its hold time


def test_exit_needed_when_directions_are_visible_and_people_must_be_accounted():
    gs = GuardState()
    d, checks = apply(away(), {"all_away": True, "unclear": [], "home": []}, gs, T, can_see_direction=True)
    assert d.state == "unknown" and "No exit" in d.reasons[0]
    on_opening(gs, {"door": "binary_sensor.garage_door", "ts": T.isoformat(), "result": "exit"}, {}, "home", T, 1)
    d, _ = apply(away(), {"all_away": True, "unclear": [], "home": []}, gs, T, can_see_direction=True)
    assert d.state == "away"
    d, _ = apply(away(), {"all_away": False, "unclear": ["Kind B"], "home": []}, gs, T, can_see_direction=True)
    assert d.state == "unknown" and "Kind B" in d.reasons[0]


def test_without_people_and_doors_the_engine_decides_as_before():
    d, checks = apply(away(), {"all_away": None}, GuardState(), T, can_see_direction=False)
    assert d.state == "away" and all(c["ok"] for c in checks)


def test_unknown_people_reset_after_long_quiet_and_exit_lowers_them():
    gs = GuardState(unknown_min=2, last_indoor=T)
    on_opening(gs, {"door": "d", "ts": T.isoformat(), "result": "exit"}, {}, "home", T, 1)
    assert gs.unknown_min == 1
    tick(gs, T + guard.UNKNOWN_RESET + timedelta(minutes=1), None)
    assert gs.unknown_min == 0


def test_explained_entry_while_home_is_no_suspicion():
    gs = GuardState()
    assert on_opening(gs, {"door": "d", "ts": T.isoformat(), "result": "entry"}, {"explained": True}, "home", T, 2) is None
    assert gs.unknown_min == 0
