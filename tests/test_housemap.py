import pytest

from bifrost_app import housemap as hm

FA = {"Ground floor": ["Hall", "Kitchen", "Living"]}


def test_valid_map_with_joined_rectangles_stairs_marks_devices():
    body = {
        "floor": "Ground floor",
        "w": 12,
        "h": 9.5,
        "rooms": [{"area": "Hall", "rects": [[0, 0, 2, 6], [2, 4, 4, 2]]}, {"area": "Kitchen", "rects": [[6, 0, 4, 4]]}],
        "stairs": [[0, 6, 2, 2]],
        "marks": [{"kind": "door", "x": 0, "y": 1, "entity_id": "binary_sensor.front_door"}, {"kind": "window", "x": 8, "y": 0}],
        "devices": [{"id": "dev:shellyhall01", "kind": "scanner", "x": 1.04, "y": 2.96}, {"id": "binary_sensor.hall_motion", "kind": "sensor", "x": 3, "y": 5}],
    }
    floor, m = hm.validate_map(body, FA)
    assert floor == "Ground floor" and m["w"] == 12 and m["h"] == 9.5
    assert m["rooms"][0]["rects"] == [[0, 0, 2, 6], [2, 4, 4, 2]]
    assert m["devices"][0] == {"id": "dev:shellyhall01", "kind": "scanner", "x": 1.0, "y": 3.0}
    assert hm.room_at(m, 3, 5) == "Hall" and hm.room_at(m, 7, 1) == "Kitchen" and hm.room_at(m, 11, 9) is None
    assert hm.placed(m)["binary_sensor.hall_motion"]["area"] == "Hall"


@pytest.mark.parametrize(
    "patch",
    [
        {"floor": "Attic"},
        {"w": 1},
        {"w": 500},
        {"w": "12"},
        {"w": float("nan")},
        {"rooms": [{"area": "Garage", "rects": [[0, 0, 1, 1]]}]},
        {"rooms": [{"area": "Hall", "rects": []}]},
        {"rooms": [{"area": "Hall", "rects": [[0, 0, 1, 1]]}, {"area": "Hall", "rects": [[2, 2, 1, 1]]}]},
        {"rooms": [{"area": "Hall", "rects": [[11, 0, 5, 1]]}]},
        {"rooms": [{"area": "Hall", "rects": [[0, 0, 1]]}]},
        {"rooms": [{"area": "Hall", "rects": [[0, 0, True, 1]]}]},
        {"marks": [{"kind": "hole", "x": 1, "y": 1}]},
        {"marks": [{"kind": "door", "x": 1, "y": 1, "entity_id": "<script>"}]},
        {"devices": [{"id": "rm -rf /", "kind": "scanner", "x": 1, "y": 1}]},
        {"devices": [{"id": "dev:a", "kind": "scanner", "x": 1, "y": 1}, {"id": "dev:a", "kind": "scanner", "x": 2, "y": 2}]},
        {"devices": [{"id": "dev:a", "kind": "laser", "x": 1, "y": 1}]},
        {"devices": [{"id": "dev:a", "kind": "scanner", "x": 99, "y": 1}]},
        {"rooms": [{"area": "Hall", "rects": [[0, 0, 0.5, 0.5]] * 300}]},
        {"devices": "x"},
    ],
)
def test_invalid_maps_are_rejected(patch):
    body = {"floor": "Ground floor", "w": 12, "h": 10, "rooms": [], **patch}
    with pytest.raises(ValueError):
        hm.validate_map(body, FA)


def test_old_cell_layout_becomes_rectangles():
    cells = {f"{x},{y}": "Hall" for x in range(4) for y in range(2)}
    cells.update({f"{x},{y}": "Kitchen" for x in range(4, 6) for y in range(3)})
    m = hm.from_cells(cells)
    rooms = {r["area"]: r["rects"] for r in m["rooms"]}
    assert rooms["Hall"] == [[0.0, 0.0, 2.0, 1.0]]
    assert rooms["Kitchen"] == [[2.0, 0.0, 1.0, 1.5]]
    assert m["w"] == 18 and m["h"] == 12


def test_clean_drops_rooms_of_deleted_areas():
    m = {"w": 10, "h": 8, "rooms": [{"area": "Hall", "rects": [[0, 0, 1, 1]]}, {"area": "Gone", "rects": [[2, 2, 1, 1]]}]}
    assert [r["area"] for r in hm.clean(m, ["Hall"])["rooms"]] == ["Hall"]


def test_scanner_candidates():
    devs = [
        {"id": "a1", "name": "Shelly Plus 1", "manufacturer": "Shelly", "area_id": "hall"},
        {"id": "b2", "name": "Proxy", "manufacturer": "Espressif"},
        {"id": "c3", "name": "Bridge", "manufacturer": "Signify"},
        {"id": "d4", "name": "Some ESPHome", "manufacturer": "Other"},
        {"id": "e5", "name": "Off", "manufacturer": "Shelly", "disabled_by": "user"},
    ]
    out = hm.scanner_candidates(devs, {"d4": {"esphome"}}, {"hall": "Hall"})
    assert [x["id"] for x in out] == ["dev:a1", "dev:b2", "dev:d4"]
    assert out[0]["area"] == "Hall"


def test_service_map_round_trip(tmp_path):
    from demo import build

    svc = build(str(tmp_path / "h.db"))
    v = svc.live_view()
    assert {s["name"] for s in v["placeable"]["scanners"]} >= {"Shelly Plus 1 Hall", "BT proxy office"}
    assert v["placeable"]["sensors"]
    floor = next(f for f in v["floors"] if f["areas"])
    lay = v["layouts"][floor["name"]]
    assert lay["map"]["rooms"] and not lay["map_saved"]  # converted from the automatic layout
    area = floor["areas"][0]["name"]
    sid = v["placeable"]["scanners"][0]["id"]
    svc.set_map({"floor": floor["name"], "w": 10, "h": 8, "rooms": [{"area": area, "rects": [[0, 0, 3, 3], [3, 0, 2, 1]]}], "devices": [{"id": sid, "kind": "scanner", "x": 1, "y": 1}]})
    lay = svc.live_view()["layouts"][floor["name"]]
    assert lay["map_saved"] and lay["map"]["devices"][0]["id"] == sid and len(lay["map"]["rooms"][0]["rects"]) == 2
    svc.reset_map(floor["name"])
    assert not svc.live_view()["layouts"][floor["name"]]["map_saved"]
    with pytest.raises(ValueError):
        svc.reset_map("nope")
