from datetime import UTC, date, datetime, timedelta

from bifrost_app import calwords, timing

P = datetime.fromisoformat


def entry(day: int, title: str, h1=8, h2=17, allday=False):
    d = datetime(2026, 3, day, tzinfo=UTC)
    if allday:
        return {"summary": title, "start": {"date": d.date().isoformat()}, "end": {"date": (d + timedelta(days=1)).date().isoformat()}}
    return {"summary": title, "start": {"dateTime": d.replace(hour=h1).isoformat()}, "end": {"dateTime": d.replace(hour=h2).isoformat()}}


def test_words_skip_sensitive_stop_words():
    assert calwords.words("Physio Weinfelden mit Kind") == ["weinfelden", "kind"]
    assert calwords.words("Spritze Impfung") == []


def test_learn_effects_per_person_house_and_day_type():
    entries = {"calendar.family": [entry(d, "Arbeiten Person B") for d in range(2, 12)] + [entry(d, "Herbstferien", allday=True) for d in range(16, 22)]}
    decisions = []
    tl = {"Person B": []}
    for d in range(2, 12):
        tl["Person B"] += [(datetime(2026, 3, d, 7, 50, tzinfo=UTC), "away"), (datetime(2026, 3, d, 17, 30, tzinfo=UTC), "home")]
    res = calwords.learn(entries, decisions, tl, {"person": "Person B", "b": "Person B"}, P)
    w = res["words"]
    assert "arbeiten" in w and w["arbeiten"]["effects"]["person"]["Person B"]["means"] == "away"
    assert w["herbstferien"]["effects"]["day_type"] is True
    assert "person" not in w  # names are not learned as words


def test_learn_missing_routine_on_holiday_days():
    entries = {"calendar.family": [entry(d, "Ferien", allday=True) for d in range(16, 23)]}
    school_days = {date(2026, 3, d) for d in range(2, 15)}
    res = calwords.learn(entries, [], {}, {}, P, routine_days={"departure": school_days})
    assert res["words"]["ferien"]["effects"]["missing"] == ["departure"]


def test_timing_arrival_and_soon():
    evs = []
    for wk in range(4):
        base = datetime(2026, 3, 2, tzinfo=UTC) + timedelta(days=7 * wk)  # Mondays
        evs.append((base.replace(hour=17, minute=30 + wk), "Person A", "home"))
    m = timing.learn(evs)
    mon = datetime(2026, 3, 30, 17, 25, tzinfo=UTC)
    e = timing.expected(m, "Person A", mon)
    assert e and abs((e["at"] - mon.replace(minute=31)).total_seconds()) < 180 * 60
    assert timing.soon(m, "Person A", e["at"])
    assert timing.expected(m, "Person A", mon + timedelta(days=1)) is None


def test_durations():
    ds = [{"ts": f"2026-03-0{d}T22:00:00+00:00", "state": "asleep"} for d in range(1, 6)] + [{"ts": f"2026-03-0{d}T06:00:00+00:00", "state": "home"} for d in range(2, 7)]
    out = timing.durations(ds, P)
    assert out["asleep"]["typical"] == 480
