"""Setup optimisations."""

from bifrost_app.optimize import suggestions


def ent(eid, name, dc=None, status="included", category="openings", role="Evidence", **kw):
    return {"entity_id": eid, "name": name, "domain": eid.split(".")[0], "device_class": dc, "status": status, "category": category, "role": role, "disabled": False, **kw}


def keys(items):
    return {(i["entity_id"], i["key"]) for i in items}


def test_doors_to_outside_become_triggers_even_with_window_class():
    items = suggestions(
        [
            ent("binary_sensor.front", "Haustüre", "window"),
            ent("binary_sensor.garage_gate", "Garagentor geschlossen", "window"),
            ent("binary_sensor.bedroom", "Eltern Tür- und Fensterkontakt", "window"),
            ent("binary_sensor.kitchen_window", "Fenster Küche", "window", role="Trigger"),
            ent("binary_sensor.terrace", "Terrace door", "door", role="Trigger"),
        ]
    )
    k = keys(items)
    assert ("binary_sensor.front", "entry_door") in k
    assert ("binary_sensor.garage_gate", "entry_door") in k
    assert ("binary_sensor.kitchen_window", "window") in k
    assert not any(e == "binary_sensor.bedroom" for e, _ in k)  # inner door: unknown until learned
    assert not any(e == "binary_sensor.terrace" for e, _ in k)  # already right
    front = next(i for i in items if i["entity_id"] == "binary_sensor.front")
    assert front["suggest"] == {"status": "included", "category": "openings", "role": "Trigger"}


def test_learned_door_roles_win_over_names():
    items = suggestions(
        [ent("binary_sensor.side", "Side contact", "door"), ent("binary_sensor.front", "Front door", "door", role="Trigger")],
        door_roles={"binary_sensor.side": {"role": "entrance"}, "binary_sensor.front": {"role": "inside_only"}},
    )
    assert keys(items) == {("binary_sensor.side", "entry_door"), ("binary_sensor.front", "inner_door")}


def test_motion_modes_robots_and_switched_off_motion():
    items = suggestions(
        [
            ent("binary_sensor.hall", "Hall motion", "motion", status="suggested", category="motion"),
            ent("binary_sensor.office", "Office presence", "presence", category="manual"),
            ent("input_boolean.guest", "Gästemodus", category="modes", role="Context"),
            ent("vacuum.robot", "Robot", category="vehicles", role="Evidence"),
            ent("binary_sensor.ignored_motion", "Old motion", "motion", status="ignored", category="motion"),
        ]
    )
    assert keys(items) == {("binary_sensor.hall", "motion_off"), ("binary_sensor.office", "motion"), ("input_boolean.guest", "mode"), ("vacuum.robot", "robot")}


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


def test_floor_length_windows_to_garden_or_terrace():
    items = suggestions(
        [
            ent("binary_sensor.hst", "Fenster Wohnen Hebeschiebetür Terrasse", "window"),
            ent("binary_sensor.garden_window", "Wohnzimmer Fenster Garten", "window"),
            ent("binary_sensor.bath_window", "Fenster Bad", "window"),
        ]
    )
    k = keys(items)
    assert ("binary_sensor.hst", "entry_door") in k  # "tür" in the name → door
    assert ("binary_sensor.garden_window", "passage_window") in k
    assert not any(e == "binary_sensor.bath_window" for e, _ in k)
    # once learning saw that nobody walks through it, the suggestion disappears
    learned = suggestions([ent("binary_sensor.garden_window", "Wohnzimmer Fenster Garten", "window")], door_roles={"binary_sensor.garden_window": {"role": "inside_only"}})
    assert learned == []


def test_learning_treats_door_named_window_contacts_as_doors():
    from bifrost_app.blocks import is_door

    assert is_door({"entity_id": "binary_sensor.hauseingang_hausture", "name": "Haustüre", "device_class": "window"})
    assert is_door({"entity_id": "binary_sensor.wohnen_fenster_garten", "name": "Fenster Garten", "device_class": "window"})
    assert not is_door({"entity_id": "binary_sensor.bad_fenster", "name": "Fenster Bad", "device_class": "window"})
    assert not is_door({"entity_id": "binary_sensor.hall_motion", "name": "Motion", "device_class": "motion", "category": "motion"})


def test_applying_a_suggestion_does_not_create_the_opposite_one():
    w = ent("binary_sensor.garden_window", "Wohnzimmer Fenster Garten", "window")
    first = suggestions([w])[0]
    w.update(first["suggest"])
    assert suggestions([w]) == []
    for e in (ent("binary_sensor.front", "Haustüre", "window"), ent("binary_sensor.k", "Fenster Küche", "window", role="Trigger")):
        s = suggestions([e])[0]
        e.update(s["suggest"])
        assert suggestions([e]) == []
