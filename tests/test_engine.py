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
    d = decide(
        [sig("person.a", "devices", "Evidence", "not_home", 90), sig("binary_sensor.hall", "motion", "Evidence", "off", 90), sig("binary_sensor.door", "openings", "Evidence", "off", 90)], S, NOW
    )
    assert d.state == AWAY and d.house_empty and d.confidence >= 85


def test_noise_is_ignored():
    d = decide([sig("person.a", "devices", "Evidence", "not_home", 90), sig("binary_sensor.hall", "motion", "Evidence", "off", 90), sig("binary_sensor.robot", "motion", "Noise", "on", 0)], S, NOW)
    assert d.state == AWAY


def test_unavailable_lowers_confidence():
    base = [sig("person.a", "devices", "Evidence", "not_home", 90), sig("binary_sensor.hall", "motion", "Evidence", "off", 90), sig("binary_sensor.x", "motion", "Evidence", "off", 90)]
    good = decide(base + [sig("binary_sensor.y", "motion", "Evidence", "off", 90)], S, NOW)
    bad = decide(base + [sig("binary_sensor.y", "motion", "Evidence", "unavailable", 90)], S, NOW)
    assert bad.data_health == 75 and bad.confidence < good.confidence


def test_no_trackers_never_says_empty():
    d = decide([sig("binary_sensor.hall", "motion", "Evidence", "off", 300)], S, NOW)
    assert d.state == UNKNOWN and not d.house_empty


def test_no_activity_sensors_never_says_empty():
    d = decide([sig("person.a", "devices", "Evidence", "not_home", 300)], S, NOW)
    assert d.state == UNKNOWN and not d.house_empty


def test_low_data_health_never_says_empty():
    sigs = [
        sig("person.a", "devices", "Evidence", "not_home", 90),
        sig("binary_sensor.a", "motion", "Evidence", "unavailable", 90),
        sig("binary_sensor.b", "motion", "Evidence", "unavailable", 90),
        sig("binary_sensor.c", "motion", "Evidence", "off", 90),
    ]
    d = decide(sigs, S, NOW)
    assert d.state == UNKNOWN and d.data_health == 50


def test_motion_that_just_stopped_counts_as_activity():
    d = decide([sig("person.a", "devices", "Evidence", "not_home", 60), sig("binary_sensor.hall", "motion", "Evidence", "off", 2)], S, NOW)
    assert d.state == LEAVING


def test_single_activity_sensor_caps_confidence():
    one = decide([sig("person.a", "devices", "Evidence", "not_home", 120), sig("binary_sensor.a", "motion", "Evidence", "off", 120)], S, NOW)
    two = decide(
        [sig("person.a", "devices", "Evidence", "not_home", 120), sig("binary_sensor.a", "motion", "Evidence", "off", 120), sig("binary_sensor.b", "openings", "Evidence", "off", 120)], S, NOW
    )
    assert one.state == two.state == AWAY and one.confidence <= 80 < two.confidence


def test_parse_time():
    assert parse_time("2026-01-01T10:00:00Z", NOW).hour == 10
    assert parse_time("garbage", NOW) == NOW
    assert parse_time(None, NOW) == NOW


def test_energy_and_air_values_are_never_activity():
    from datetime import UTC, datetime, timedelta

    from bifrost_app.engine import Settings, Signal, decide

    now = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    old = now - timedelta(hours=2)
    sigs = [
        Signal("device_tracker.a", "Phone", "devices", "Evidence", "not_home", old),
        Signal("binary_sensor.m1", "Motion 1", "motion", "Evidence", "off", old),
        Signal("binary_sensor.m2", "Motion 2", "motion", "Evidence", "off", old),
        Signal("sensor.server_power", "Server power", "energy", "Evidence", "23.4", now - timedelta(seconds=20)),
        Signal("sensor.co2", "CO2", "climate", "Evidence", "612", now - timedelta(seconds=30)),
    ]
    d = decide(sigs, Settings(10, 15), now)
    assert d.state == "away" and not any("Server power" in r for r in d.reasons)


def test_open_blind_or_light_left_on_is_not_activity_right_now():
    """A blind opened in the morning or a light left on must not keep the house "home" all day."""
    sigs = [
        sig("person.a", "devices", "Evidence", "not_home", 120),
        sig("binary_sensor.hall", "motion", "Evidence", "off", 120),
        sig("cover.living", "manual", "Evidence", "open", 240),
        sig("light.kitchen", "manual", "Evidence", "on", 180),
    ]
    d = decide(sigs, S, NOW)
    assert d.state != HOME and not any("Activity right now" in r for r in d.reasons)


def test_fresh_manual_change_is_activity_right_now():
    sigs = [sig("person.a", "devices", "Evidence", "not_home", 120), sig("light.kitchen", "manual", "Evidence", "on", 1)]
    d = decide(sigs, S, NOW)
    assert d.state == HOME and any("Activity right now" in r for r in d.reasons)


def test_unreliable_sensor_firing_never_allows_empty():
    """Learning may only make Bifrost more careful: a motion sensor learned as unreliable is not activity,
    but while it fires Bifrost must not say "empty" (fail closed)."""
    sigs = [sig("person.a", "devices", "Evidence", "not_home", 120), sig("binary_sensor.hall", "motion", "Evidence", "on", 1), sig("binary_sensor.door", "openings", "Evidence", "off", 120)]
    d = decide(sigs, S, NOW, unreliable={"binary_sensor.hall"})
    assert d.state == UNKNOWN and not d.house_empty and d.ignored_unreliable == ["binary_sensor.hall"]
    sigs[1] = sig("binary_sensor.hall", "motion", "Evidence", "off", 120)
    assert decide(sigs, S, NOW, unreliable={"binary_sensor.hall"}).state == AWAY
