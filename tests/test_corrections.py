"""0.17: one-tap corrections, blame by share, fading."""

from datetime import UTC, datetime, timedelta

from bifrost_app import corrections as c

NOW = datetime(2026, 11, 28, 12, tzinfo=UTC)


def _p(x):
    return datetime.fromisoformat(x)


def test_half_life_shortens_with_learning_progress():
    assert c.half_life(0) == c.HL_MAX and c.half_life(1) == c.HL_MIN
    assert c.HL_MIN < c.half_life(0.5) < c.HL_MAX
    assert c.progress([{"value": 5, "need": 10}, {"value": 30, "need": 10}]) == 0.75


def test_fade_halves_per_half_life_and_stops_below_floor():
    assert c.fade(NOW, NOW, 10) == 1.0
    assert abs(c.fade(NOW - timedelta(days=10), NOW, 10) - 0.5) < 0.01
    assert c.fade(NOW - timedelta(days=40), NOW, 10) == 0.0  # 1/16 < 0.1 → no longer counts


def test_blame_is_shared_by_how_strongly_signals_pushed_the_wrong_way():
    parts = [{"entity_id": "m.hall", "weight": 3.0}, {"entity_id": "m.kitchen", "weight": 1.0}, {"entity_id": "t.phone", "weight": -2.0}]
    # said home, really away → the signals pushing towards home are to blame
    assert c.blame("home", "away", parts) == [{"entity_id": "m.hall", "share": 0.75}, {"entity_id": "m.kitchen", "share": 0.25}]
    # said away, really home → the phone saying "away" is to blame
    assert c.blame("away", "home", parts) == [{"entity_id": "t.phone", "share": 1.0}]
    # home vs asleep is not a presence mistake
    assert c.blame("home", "asleep", parts) == []
    # without an evidence model: what changed just before shares the blame
    assert c.blame("home", "away", [], ["m.hall", "m.door"]) == [{"entity_id": "m.hall", "share": 0.5}, {"entity_id": "m.door", "share": 0.5}]


def test_effective_weights_fade_and_old_labels_drop_out_of_hindsight():
    labels = [
        {"ts": NOW.isoformat(), "said": "home", "actual": "away", "blame": [{"entity_id": "m.hall", "share": 1.0}]},
        {"ts": (NOW - timedelta(days=20)).isoformat(), "said": "home", "actual": "away", "blame": [{"entity_id": "m.hall", "share": 0.5}]},
        {"ts": (NOW - timedelta(days=200)).isoformat(), "said": "away", "actual": "home"},
        {"ts": NOW.isoformat(), "said": "home", "actual": "away", "person": "p1", "trackers": ["t.phone"]},
    ]
    e = c.effective(labels, NOW, 20, _p)
    assert e["culprits"]["m.hall"] == 1.25  # 1 + 0.5 × 0.5
    assert e["trackers"] == {"t.phone": 1.0}
    assert len(e["labels"]) == 2 and all(lab["_w"] >= 0.5 for lab in e["labels"])  # the 200-day-old one no longer counts


def test_repeated_blame_on_different_days_only():
    lab = lambda d, s: {"ts": (NOW + timedelta(days=d)).isoformat(), "blame": [{"entity_id": "m.hall", "share": s}]}  # noqa: E731
    assert c.repeated([lab(0, 1), lab(0, 1), lab(0, 1)], _p) == []  # same day
    assert c.repeated([lab(0, 1), lab(1, 0.2), lab(2, 1)], _p) == []  # one with a tiny share
    assert c.repeated([lab(0, 1), lab(1, 0.5), lab(2, 1)], _p) == ["m.hall"]


def test_view_counts_mistakes_and_shows_current_weight():
    labels = [
        {"ts": NOW.isoformat(), "said": "away", "actual": "home", "blame": [{"entity_id": "t.phone", "share": 1.0}]},
        {"ts": (NOW - timedelta(days=45)).isoformat(), "said": "home", "actual": "away", "blame": [{"entity_id": "m.hall", "share": 1.0}]},
    ]
    v = c.view(labels, NOW, 30, _p, {"t.phone": "Phone A"}, {})
    assert v["total"] == 2 and v["month"] == 1 and v["half_life"] == 30
    assert v["items"][0]["weight"] == 1.0 and v["items"][0]["blame"][0]["name"] == "Phone A"
    assert 0.3 < v["items"][1]["weight"] < 0.4
    assert v["signals"][0]["entity_id"] == "t.phone"
