from bifrost_app.categories import STATUS_IGNORED, STATUS_INCLUDED, STATUS_SUGGESTED, STATUS_UNKNOWN, is_valid_category, is_valid_role
from bifrost_app.classifier import EntityInfo, classify


def cl(eid, **kw):
    return classify(EntityInfo(eid, **kw))


def test_person_is_included_evidence():
    r = cl("person.example_user", name="Example User")
    assert (r.category, r.role, r.status) == ("devices", "Evidence", STATUS_INCLUDED)
    assert r.reasons


def test_phone_tracker():
    r = cl("device_tracker.example_iphone", name="Example iPhone")
    assert r.category == "devices" and r.status == STATUS_INCLUDED


def test_stationary_devices_are_ignored():
    assert cl("device_tracker.living_room_ipad").status == STATUS_IGNORED
    assert cl("device_tracker.office_printer").status == STATUS_IGNORED


def test_random_mac_tracker_is_unknown():
    r = cl("device_tracker.unifi_default_aa_bb_cc_dd_ee_ff")
    assert r.status == STATUS_UNKNOWN and r.category == "devices"


def test_irrelevant_domains():
    for eid in ("update.core", "automation.morning", "scene.cozy", "button.restart", "sun.sun"):
        assert cl(eid).status == STATUS_IGNORED, eid


def test_system_sensors_ignored_but_co2_not():
    assert cl("sensor.shelly_wifi_signal").status == STATUS_IGNORED
    assert cl("sensor.office_co2", device_class="carbon_dioxide").relevant


def test_motion_sensor_included():
    r = cl("binary_sensor.hallway_motion", device_class="motion", name="Hallway motion")
    assert r.category == "motion" and r.status == STATUS_INCLUDED


def test_outdoor_motion_is_not_auto_included():
    r = cl("binary_sensor.garden_motion", device_class="motion", name="Garden motion")
    assert r.status != STATUS_INCLUDED


def test_modes():
    assert cl("input_boolean.guest_mode").role == "Blocker"
    assert cl("input_boolean.sleep_mode").role == "Blocker"
    assert cl("input_boolean.vacation_mode").role == "Context"
    assert cl("switch.random_relay_3").status == STATUS_IGNORED


def test_robot_is_noise():
    assert cl("vacuum.downstairs").role == "Noise"


def test_birthday_calendar_ignored_other_calendar_context():
    assert cl("calendar.family_birthdays").status == STATUS_IGNORED
    r = cl("calendar.example_work")
    assert r.category == "calendar" and r.role == "Context"


def test_light_is_suggested_not_auto():
    assert cl("light.kitchen").status in (STATUS_UNKNOWN, STATUS_SUGGESTED)


def test_disabled_and_unavailable_are_explained():
    r = cl("binary_sensor.hall_motion", device_class="motion", disabled=True, available=False)
    text = " ".join(r.reasons)
    assert "Disabled" in text and "unavailable" in text


def test_every_result_uses_valid_category_and_role():
    samples = [
        "person.a",
        "device_tracker.b_phone",
        "binary_sensor.c",
        "sensor.d_power",
        "light.e",
        "cover.f",
        "climate.g",
        "media_player.h",
        "lock.i",
        "alarm_control_panel.j",
        "calendar.k",
        "weather.l",
        "event.m_doorbell",
        "unknown_domain.x",
    ]
    for eid in samples:
        r = cl(eid)
        assert r.category is None or is_valid_category(r.category), eid
        assert r.role is None or is_valid_role(r.role), eid
        assert 0 <= r.confidence <= 1


# --- regressions found with a real installation (names anonymised) ---------------
def test_location_is_not_a_cat():
    assert cl("sensor.example_phone_geocoded_location").category != "vehicles"


def test_christmas_mode_is_not_night_mode():
    assert cl("switch.living_weihnachtsmodus", name="Weihnachtsmodus").role != "Blocker"
    assert cl("switch.example_nachttisch_do_not_disturb").role != "Blocker"
    assert cl("switch.central_nachtmodus", name="Nachtmodus").role == "Blocker"


def test_guest_toilet_is_not_guest_mode():
    assert cl("switch.gaste_wc_comfort_override", name="Gäste WC Comfort Override").role != "Blocker"
    assert cl("switch.gaste_aktiviert", name="Gäste aktiviert").role == "Blocker"


def test_robot_statistics_ignored_status_kept():
    assert cl("sensor.robot_s6_remaining_brush_time").status == STATUS_IGNORED
    assert cl("sensor.roborock_total_cleanings").status == STATUS_IGNORED
    assert cl("sensor.roborock_status").role == "Noise"


def test_headphones_are_not_media_evidence():
    assert cl("media_player.example_linkbuds", name="Example LinkBuds").status == STATUS_IGNORED
    r = cl("media_player.living_room_tv")
    assert r.role == "Evidence" and r.status == STATUS_INCLUDED


def test_infrastructure_trackers_ignored():
    for eid in ("device_tracker.shelly_pro_3em_wallbox", "device_tracker.v_zug_oven", "device_tracker.hue_bridge_pro"):
        assert cl(eid).status == STATUS_IGNORED, eid


def test_weather_binary_sensors_ignored():
    assert cl("binary_sensor.outdoor_regen", name="Regen").status == STATUS_IGNORED


def test_nightlight_is_not_sleep_mode():
    assert cl("switch.wled_nightlight").role != "Blocker"
