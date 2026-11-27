from datetime import datetime, timedelta

from sim import META, SIDES, household

from bifrost_app import hindsight as hs

P = datetime.fromisoformat


def run(days=14, trouble=False):
    s = household(days, trouble=trouble)
    return s, hs.label(s.events, META, SIDES)


def test_departures_and_arrivals_are_found_without_any_decision():
    s, r = run()
    empty = [x for x in r["segments"] if x["label"] == hs.EMPTY]
    # every working day: everybody leaves in the morning, Person B is back at noon
    assert len(empty) >= 14 and len(r["departures"]) == len(r["arrivals"]) == len(empty)
    assert all(x["strength"] == hs.STRONG and x["why"] == "exit_then_entry" for x in empty)
    assert r["stats"]["empty_h"] > 40


def test_animals_do_not_break_an_empty_stretch_and_become_disturbances():
    s, r = run()
    assert r["disturbances"] and {d["entity_id"] for d in r["disturbances"]} == {"binary_sensor.motion_hallway"}


def test_a_child_without_phone_who_stayed_inside_is_home_and_the_wrong_empty_is_found():
    s, r = run(days=14, trouble=True)
    stayed = [x for x in r["segments"] if x["why"] == "stayed_inside"]
    assert stayed
    wrong = hs.wrong_empty(r, s.decisions, P)
    assert len(wrong) == 2  # days 3 and 10: the rules said "away" while Kind B was upstairs
    assert all(w["why"] == "stayed_inside" for w in wrong)
    assert not hs.wrong_empty(run()[1], household(14).decisions, P)  # a normal fortnight has none


def test_owner_label_and_alarm_panel_win():
    s, r = run(3)
    gap = next(x for x in r["segments"] if x["label"] == hs.EMPTY)
    mid = gap["start"] + (gap["end"] - gap["start"]) / 2
    r2 = hs.label(s.events, META, SIDES, owner_labels=[{"ts": mid.isoformat(), "actual": "home"}])
    assert hs.label_at(r2, mid) == hs.HOME
    ev = s.events + [
        {"ts": (mid - timedelta(minutes=1)).isoformat(), "entity_id": "alarm_control_panel.house", "kind": "on", "state": "armed_away"},
        {"ts": (mid + timedelta(minutes=1)).isoformat(), "entity_id": "alarm_control_panel.house", "kind": "off", "state": "disarmed"},
    ]
    r3 = hs.label(ev, META, SIDES, owner_labels=[{"ts": mid.isoformat(), "actual": "home"}])
    assert hs.label_at(r3, mid) == hs.HOME  # the owner's word is last


def test_decision_timeline_from_segments():
    s, r = run(2)
    dec = hs.to_decisions(r)
    assert {d["state"] for d in dec} <= {"home", "away", "unknown"} and any(d["state"] == "away" for d in dec)
    assert dec == sorted(dec, key=lambda d: d["ts"])
