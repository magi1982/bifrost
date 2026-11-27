"""Setup optimisations."""

from bifrost_app.optimize import suggestions


def ent(eid, name, dc=None, status="included", category="openings", role="Evidence", **kw):
    return {"entity_id": eid, "name": name, "domain": eid.split(".")[0], "device_class": dc, "status": status, "category": category, "role": role, "disabled": False, **kw}


def keys(items):
    return {(i["entity_id"], i["key"]) for i in items}


def test_openings_and_motion_categories_and_switched_off():
    items = suggestions(
        [
            ent("binary_sensor.front", "Haustüre", "window", status="suggested", category="openings"),
            ent("binary_sensor.k", "Fenster Küche", "window", category="manual"),
            ent("binary_sensor.terrace", "Terrace door", "door"),
            ent("binary_sensor.hall", "Hall motion", "motion", status="suggested", category="motion"),
            ent("binary_sensor.office", "Office presence", "presence", category="manual"),
            ent("binary_sensor.old", "Old motion", "motion", status="ignored", category="motion"),
        ]
    )
    assert keys(items) == {
        ("binary_sensor.front", "opening_off"),
        ("binary_sensor.k", "opening"),
        ("binary_sensor.hall", "motion_off"),
        ("binary_sensor.office", "motion"),
    }
    assert all("role" not in i["suggest"] for i in items)


def test_modes_robots_alarm_identity():
    items = suggestions(
        [
            ent("input_boolean.guest", "Gästemodus", category="manual"),
            ent("input_boolean.holiday", "Ferienmodus", category="mode_home"),
            ent("vacuum.robot", "Robot", category="vehicles"),
            ent("alarm_control_panel.a", "Alarm", category="manual"),
            ent("sensor.door_last_user", "Haustür letzter Benutzer", category=None, status="suggested", guess_category="access"),
        ]
    )
    assert keys(items) == {
        ("input_boolean.guest", "mode_home"),
        ("input_boolean.holiday", "mode_away"),
        ("vacuum.robot", "robot"),
        ("alarm_control_panel.a", "alarm"),
        ("sensor.door_last_user", "identity"),
    }


def test_applying_a_suggestion_does_not_create_the_opposite_one():
    for e in (
        ent("binary_sensor.front", "Haustüre", "window", status="suggested", category="openings"),
        ent("input_boolean.guest", "Gästemodus", category="manual"),
        ent("binary_sensor.office", "Office presence", "presence", category="manual"),
    ):
        s = suggestions([e])[0]
        e.update(s["suggest"])
        assert suggestions([e]) == []


def test_roles_are_derived_not_set():
    from bifrost_app.categories import derive_role

    assert derive_role("access", None, None) == "Identity"
    assert derive_role("mode_home", "manual", "Evidence") == "Blocker"
    assert derive_role("mode_away", None, None) == "Context"
    assert derive_role("openings", "openings", "Evidence", "entrance") == "Trigger"  # learned entrance wins
    assert derive_role("openings", "openings", "Trigger", "inside_only") == "Evidence"
    assert derive_role("openings", "openings", "Noise") == "Noise"  # doorbell: classifier knows best
    assert derive_role("motion", "openings", "Trigger") == "Evidence"  # user changed the category → default
    assert derive_role(None, "motion", "Evidence") is None


def test_disabled_dead_and_dismissed():
    items = suggestions(
        [ent("binary_sensor.a", "A", "motion", category="motion", disabled=True), ent("binary_sensor.b", "B", "motion", category="motion")],
        doctor=[{"entity_id": "binary_sensor.b", "problem": "dead", "detail": "no activity in 20 days"}],
    )
    assert keys(items) == {("binary_sensor.a", "disabled_in_ha"), ("binary_sensor.b", "doctor_dead")}
    assert suggestions([ent("binary_sensor.a", "A", "motion", category="motion", disabled=True)], dismissed={"binary_sensor.a|disabled_in_ha"}) == []


def test_api_flow_on_demo(tmp_path):
    from demo import build

    svc = build(str(tmp_path / "d.db"))
    v = svc.optimizations_view()
    assert isinstance(v["items"], list)
    for it in v["items"]:
        svc.dismiss_optimization(it["entity_id"], it["key"])
    assert svc.optimizations_view()["items"] == []
    assert svc.reset_optimizations() == {"dismissed": 0}


def test_learning_treats_door_named_window_contacts_as_doors():
    from bifrost_app.blocks import is_door

    assert is_door({"entity_id": "binary_sensor.hauseingang_hausture", "name": "Haustüre", "device_class": "window"})
    assert is_door({"entity_id": "binary_sensor.wohnen_fenster_garten", "name": "Fenster Garten", "device_class": "window"})
    assert not is_door({"entity_id": "binary_sensor.bad_fenster", "name": "Fenster Bad", "device_class": "window"})
    assert not is_door({"entity_id": "binary_sensor.hall_motion", "name": "Motion", "device_class": "motion", "category": "motion"})


def test_tesla_bluetooth_and_disabled_reason():
    from bifrost_app.classifier import EntityInfo, classify

    tesla = classify(EntityInfo("device_tracker.s3ea36bcb2154c537c_bb27", "S3ea36bcb2154c537C BB27"))
    assert (tesla.category, tesla.role) == ("vehicles", "Evidence") and "Tesla" in tesla.reasons[0]
    off = classify(EntityInfo("device_tracker.car_wifi", "Car", disabled=True, disabled_by="integration"))
    assert any("Disabled by its integration" in r for r in off.reasons)
    phone = classify(EntityInfo("device_tracker.s_phone", "Sam phone"))
    assert phone.category == "devices"


def test_old_roles_are_migrated_on_scan(tmp_path):
    from demo import build

    svc = build(str(tmp_path / "m.db"))
    st = svc.store
    with st._db:  # rows as written by ≤ 0.5 (the category "modes" no longer exists)
        for eid, cat, role in (("binary_sensor.motion_dead", "motion", "Noise"), ("input_boolean.night_mode", "modes", "Blocker"), ("calendar.family", "modes", "Context")):
            st._db.execute(
                "INSERT OR REPLACE INTO entity_settings(entity_id, status, category, role, updated) VALUES (?,?,?,?,?)",
                (eid, "included", cat, role, "2026-01-01T00:00:00+00:00"),
            )
    svc.scan()
    ents = svc.snap.entities
    assert ents["binary_sensor.motion_dead"].status == "ignored"
    assert ents["input_boolean.night_mode"].category == "mode_home" and ents["input_boolean.night_mode"].role == "Blocker"
    assert ents["calendar.family"].category == "mode_away"
    assert all(v["role"] is None for v in st.get_overrides().values())
