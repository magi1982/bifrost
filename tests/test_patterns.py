from datetime import UTC, datetime, timedelta

from bifrost_app import calendars as cal
from bifrost_app import patterns as pat

T = datetime(2026, 1, 5, 7, 0, tzinfo=UTC)


def P(v):
    return datetime.fromisoformat(v)


def ev(t, eid, state):
    return {"ts": t.isoformat(), "entity_id": eid, "state": state}


def dec(t, state):
    return {"ts": t.isoformat(), "state": state, "confidence": 90}


def build(days, extra_door=0):
    events, decisions = [], []
    for i in range(days):
        d = T + timedelta(days=i)
        decisions += [dec(d, "home"), dec(d + timedelta(minutes=20), "leaving"), dec(d + timedelta(minutes=40), "away"), dec(d + timedelta(hours=9), "home")]
        events += [
            ev(d + timedelta(minutes=2), "calendar.work", "on"),
            ev(d + timedelta(minutes=10), "binary_sensor.door", "on"),
            ev(d + timedelta(minutes=14), "person.a", "not_home"),
            ev(d + timedelta(minutes=30), "binary_sensor.door", "off"),
        ]
    for i in range(extra_door):
        t = T + timedelta(days=i, hours=13)
        events += [ev(t, "calendar.work", "on"), ev(t + timedelta(minutes=5), "binary_sensor.door", "on"), ev(t + timedelta(minutes=8), "person.a", "not_home")]
    return events, decisions


def test_step_tokens():
    assert pat.step_token("person.a", "not_home") == "person.a:away"
    assert pat.step_token("person.a", "home") == "person.a:home"
    assert pat.step_token("binary_sensor.d", "on") == "binary_sensor.d:on"
    assert pat.step_token("binary_sensor.d", "off") is None


def test_mines_three_step_departure_with_gaps():
    events, decisions = build(6)
    found = [p for p in pat.mine(events, decisions, P, {"person.a": "Person A"}) if p.outcome == "departure"]
    assert len(found) == 1
    p = found[0]
    assert p.tokens == ["calendar.work:on", "binary_sensor.door:on", "person.a:away"]
    assert p.gaps == [8, 4] and p.lead == 6 and p.support == 6 and p.precision == 1.0
    d = p.to_dict()
    assert d["steps"][2]["name"] == "Person A" and d["steps"][1]["gap_before"] == 8


def test_needs_enough_support():
    events, decisions = build(4)
    assert pat.mine(events, decisions, P) == []


def test_low_precision_is_rejected():
    events, decisions = build(6, extra_door=6)  # same steps at noon without leaving
    assert [p for p in pat.mine(events, decisions, P) if p.outcome == "departure" and len(p.tokens) == 3] == []


def test_progress():
    toks = ["calendar.work:on", "binary_sensor.door:on", "person.a:away"]
    now = T + timedelta(minutes=12)
    recent = [(T + timedelta(minutes=2), "calendar.work:on"), (T + timedelta(minutes=10), "binary_sensor.door:on")]
    assert pat.progress(toks, recent, now) == 2
    assert pat.progress(toks, recent, now + timedelta(hours=2)) == 0


def test_calendar_keywords_and_share():
    assert cal.keywords("Büro Meeting mit Team in Zürich") == {"büro", "team", "zürich"}
    ds = [dec(T, "home"), dec(T + timedelta(hours=1), "away"), dec(T + timedelta(hours=3), "home")]
    assert cal.away_share(T, T + timedelta(hours=4), ds, P) == 0.5
    st = cal.learn("calendar.x", [{"summary": "Büro", "start": {"dateTime": (T + timedelta(hours=1)).isoformat()}, "end": {"dateTime": (T + timedelta(hours=3)).isoformat()}}] * 3, ds, P)
    assert st["keywords"]["büro"] == [3, 3]
    ins = cal.insights(st)
    assert ins[0]["means_away"]
    assert cal.active_hint([("calendar.x", "Büro Tag")], {"calendar.x": st})
    assert cal.active_hint([("calendar.x", "Arzt")], {"calendar.x": st}) == []
