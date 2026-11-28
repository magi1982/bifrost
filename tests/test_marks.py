"""Doors and windows on the house map: turning, bound contacts, live state."""

import pytest

from bifrost_app import housemap as hm

FA = {"Ground floor": ["Hall", "Kitchen"]}


def _body(marks):
    return {"floor": "Ground floor", "w": 10, "h": 8, "rooms": [{"area": "Hall", "rects": [[0, 0, 4, 4]]}], "marks": marks}


def test_rotation_defaults_to_zero_and_keeps_ninety():
    _, m = hm.validate_map(_body([{"kind": "door", "x": 4, "y": 1}, {"kind": "window", "x": 4, "y": 2, "rot": 90}]), FA)
    assert [x["rot"] for x in m["marks"]] == [0, 90]


@pytest.mark.parametrize("rot", [45, 180, 270, -90, True, "90", 90.5, None])
def test_other_rotations_are_rejected(rot):
    with pytest.raises(ValueError):
        hm.validate_map(_body([{"kind": "door", "x": 1, "y": 1, "rot": rot}]), FA)


def test_old_maps_without_rotation_stay_valid():
    _, m = hm.validate_map(_body([{"kind": "window", "x": 2, "y": 0, "entity_id": "binary_sensor.hall_window"}]), FA)
    assert m["marks"][0] == {"kind": "window", "x": 2, "y": 0, "rot": 0, "entity_id": "binary_sensor.hall_window"}


def test_contact_must_be_a_known_opening_sensor():
    known = {"binary_sensor.hall_window"}
    _, m = hm.validate_map(_body([{"kind": "window", "x": 2, "y": 0, "entity_id": "binary_sensor.hall_window"}]), FA, known)
    assert m["marks"][0]["entity_id"] == "binary_sensor.hall_window"
    for eid in ("binary_sensor.hall_motion", "light.hall", "switch.alarm"):
        with pytest.raises(ValueError, match="contact"):
            hm.validate_map(_body([{"kind": "window", "x": 2, "y": 0, "entity_id": eid}]), FA, known)
    _, m = hm.validate_map(_body([{"kind": "door", "x": 2, "y": 0}]), FA, set())  # no contact is fine
    assert "entity_id" not in m["marks"][0]


@pytest.mark.parametrize(
    ("eid", "dc", "cat", "ok"),
    [
        ("binary_sensor.a", "window", None, True),
        ("binary_sensor.a", "door", None, True),
        ("binary_sensor.a", "garage_door", None, True),
        ("binary_sensor.a", "Opening", None, True),
        ("binary_sensor.a", None, "openings", True),
        ("binary_sensor.a", "motion", "motion", False),
        ("cover.a", "window", "openings", False),
        ("sensor.a", "door", None, False),
    ],
)
def test_is_opening(eid, dc, cat, ok):
    assert hm.is_opening(eid, dc, cat) is ok


def test_service_openings_live_state_and_save(tmp_path):
    from demo import build

    svc = build(str(tmp_path / "h.db"))
    v = svc.live_view()
    ops = {x["id"]: x for x in v["openings"]}
    assert ops, "demo household has door/window contacts"
    assert all(x["id"].startswith("binary_sensor.") for x in ops.values())
    assert all(set(x) == {"id", "name", "area", "state", "ts"} for x in ops.values())
    eid = next(iter(ops))
    floor = next(f for f in v["floors"] if f["areas"])
    area = floor["areas"][0]["name"]
    base = {"floor": floor["name"], "w": 10, "h": 8, "rooms": [{"area": area, "rects": [[0, 0, 4, 4]]}]}
    svc.set_map({**base, "marks": [{"kind": "window", "x": 4, "y": 1, "rot": 90, "entity_id": eid}]})
    mk = svc.live_view()["layouts"][floor["name"]]["map"]["marks"][0]
    assert mk == {"kind": "window", "x": 4, "y": 1, "rot": 90, "entity_id": eid}
    with pytest.raises(ValueError, match="contact"):
        svc.set_map({**base, "marks": [{"kind": "window", "x": 4, "y": 1, "entity_id": "binary_sensor.not_a_contact"}]})
