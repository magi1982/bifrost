from datetime import UTC, datetime, timedelta

from bifrost_app.engine import ARRIVING, ASLEEP, AWAY, HOME, LEAVING, UNKNOWN, Settings, Signal, decide, parse_time

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
S = Settings(phone_away_minutes=10, no_motion_minutes=15)


def sig(eid, cat, role, state, mins_ago=60):
    return Signal(eid, eid, cat, role, state, NOW - timedelta(minutes=mins_ago))


def test_no_signals_unknown():
    d = decide([], S, NOW)
    assert d.state == UNKNOWN and d.confidence == 0 and not d.house_empty


def test_phone_home():
    d = decide([sig("person.a", "devices", "Evidence", "home"), sig("person.b", "devices", "Evidence", "not_home")], S, NOW)
    assert d.state == HOME and d.people_home == ["person.a"]


def test_arriving():
    d = decide([sig("person.a", "devices", "Evidence", "home", 1), sig("binary_sensor.door", "openings", "Trigger", "on", 1)], S, NOW)
    assert d.state == ARRIVING


def test_blocker_sleep_beats_everything():
    d = decide([sig("person.a", "devices", "Evidence", "not_home"), sig("input_boolean.sleep_mode", "modes", "Blocker", "on")], S, NOW)
    assert d.state == ASLEEP and not d.house_empty


def test_guest_blocker_is_home():
    d = decide([sig("input_boolean.guest_mode", "modes", "Blocker", "on")], S, NOW)
    assert d.state == HOME


def test_motion_without_phone_is_home():
    d = decide([sig("person.a", "devices", "Evidence", "not_home"), sig("binary_sensor.hall", "motion", "Evidence", "on", 0)], S, NOW)
    assert d.state == HOME and any("without a tracked device" in r for r in d.reasons)


def test_leaving_within_waiting_time():
    d = decide([sig("person.a", "devices", "Evidence", "not_home", 5), sig("binary_sensor.hall", "motion", "Evidence", "off", 5)], S, NOW)
    assert d.state == LEAVING and not d.house_empty


def test_away_after_waiting_time():
    d = decide([sig("person.a", "devices", "Evidence", "not_home", 90), sig("binary_sensor.hall", "motion", "Evidence", "off", 90)], S, NOW)
    assert d.state == AWAY and d.house_empty and d.confidence >= 85


def test_noise_is_ignored():
    d = decide([sig("person.a", "devices", "Evidence", "not_home", 90), sig("binary_sensor.robot", "motion", "Noise", "on", 0)], S, NOW)
    assert d.state == AWAY


def test_unavailable_lowers_confidence():
    good = decide([sig("person.a", "devices", "Evidence", "not_home", 90), sig("binary_sensor.hall", "motion", "Evidence", "off", 90)], S, NOW)
    bad = decide([sig("person.a", "devices", "Evidence", "not_home", 90), sig("binary_sensor.hall", "motion", "Evidence", "unavailable", 90)], S, NOW)
    assert bad.data_health == 50 and bad.confidence < good.confidence


def test_no_trackers_long_quiet_is_away_but_capped():
    d = decide([sig("binary_sensor.hall", "motion", "Evidence", "off", 300)], S, NOW)
    assert d.state == AWAY and d.confidence <= 80


def test_parse_time():
    assert parse_time("2026-01-01T10:00:00Z", NOW).hour == 10
    assert parse_time("garbage", NOW) == NOW
    assert parse_time(None, NOW) == NOW
