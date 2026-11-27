from datetime import UTC, datetime, timedelta

from bifrost_app.preprocess import (
    DuplicateDetector,
    Edge,
    EdgeFilter,
    blur_for,
    simultaneous,
)

T0 = datetime(2026, 1, 5, 7, 0, tzinfo=UTC)


def at(s: float) -> datetime:
    return T0 + timedelta(seconds=s)


def kinds(edges):
    return [e.kind for e in edges]


def test_first_value_is_not_an_edge_then_rising_and_falling():
    f = EdgeFilter()
    assert f.feed("binary_sensor.hall", "off", at(0)) == []
    assert kinds(f.feed("binary_sensor.hall", "on", at(10))) == ["on"]
    assert f.feed("binary_sensor.hall", "on", at(20)) == []  # no change, no edge
    assert kinds(f.feed("binary_sensor.hall", "off", at(30))) == ["off"]


def test_flicker_within_debounce_is_ignored():
    f = EdgeFilter(debounce_seconds=2)
    f.feed("binary_sensor.hall", "off", at(0))
    f.feed("binary_sensor.hall", "on", at(5))
    f.feed("binary_sensor.hall", "off", at(6))
    assert f.feed("binary_sensor.hall", "on", at(7)) == []  # 1 s later: flicker
    assert f.flicker_count() == 1
    f.feed("binary_sensor.hall", "off", at(8))
    assert kinds(f.feed("binary_sensor.hall", "on", at(20))) == ["on"]  # real new activity


def test_unavailable_is_a_gap_not_off():
    f = EdgeFilter()
    f.feed("binary_sensor.door", "off", at(0))
    assert kinds(f.feed("binary_sensor.door", "unavailable", at(5))) == ["gap"]
    assert f.feed("binary_sensor.door", "off", at(9)) == []  # back after gap: no fake edge
    assert kinds(f.feed("binary_sensor.door", "on", at(20))) == ["on"]


def test_trackers_only_change_between_home_and_away():
    f = EdgeFilter()
    f.feed("device_tracker.phone_a", "home", at(0))
    assert kinds(f.feed("device_tracker.phone_a", "not_home", at(10))) == ["away"]
    assert f.feed("device_tracker.phone_a", "Work", at(20)) == []  # another zone is still away
    assert kinds(f.feed("device_tracker.phone_a", "home", at(30))) == ["home"]


def test_numbers_are_skipped_other_values_become_changes():
    f = EdgeFilter()
    assert f.feed("sensor.power", "312.4", at(0)) == []
    assert f.feed("sensor.power", "318", at(1)) == []
    assert kinds(f.feed("select.scene", "Evening", at(2))) == ["change"]
    assert f.feed("select.scene", "Evening", at(3)) == []


def test_simultaneous_uses_the_larger_blur():
    assert simultaneous(at(0), at(1.0))
    assert not simultaneous(at(0), at(3.0))
    assert simultaneous(at(0), at(8), blur_a=blur_for("private_ble_device"))
    assert blur_for("unknown_integration") == 1.5


def test_duplicate_detector_finds_sensors_that_always_fire_together():
    d = DuplicateDetector(window_seconds=1)
    for i in range(25):
        base = i * 60
        d.feed(Edge(at(base), "binary_sensor.hall_loxone", "on", "on"))
        d.feed(Edge(at(base + 0.4), "binary_sensor.hall_mqtt", "on", "on"))
        if i % 3 == 0:
            d.feed(Edge(at(base + 0.5), "binary_sensor.kitchen", "on", "on"))
        d.feed(Edge(at(base + 30), "binary_sensor.kitchen", "off", "off"))  # off edges are ignored
    found = d.candidates(min_events=20)
    assert [(c["a"], c["b"]) for c in found] == [("binary_sensor.hall_loxone", "binary_sensor.hall_mqtt")]
    assert found[0]["ratio"] == 1.0


def test_duplicate_detector_needs_enough_events():
    d = DuplicateDetector()
    for i in range(5):
        d.feed(Edge(at(i * 60), "binary_sensor.a", "on", "on"))
        d.feed(Edge(at(i * 60 + 0.2), "binary_sensor.b", "on", "on"))
    assert d.candidates(min_events=20) == []
