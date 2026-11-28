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
    assert m["devices"][0] == {"id": "dev:shellyhall01", "kind": "scanner", "x": 1.04, "y": 2.96}  # kept to the centimetre
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
    svc.reset_map(floor["name"])  # 0.18: no longer deletes – the suggestion becomes a new version
    lay = svc.live_view()["layouts"][floor["name"]]
    assert lay["map_saved"] and not lay["map"]["devices"]
    assert [v["source"] for v in svc.map_versions(floor["name"])["versions"]][:2] == ["suggestion", "save"]
    with pytest.raises(ValueError):
        svc.reset_map("nope")


def test_outside_areas_hull_and_layers():
    fa = {"Ground floor": ["Hall"], "Outside": ["Garden"]}
    body = {
        "floor": "Ground floor",
        "w": 24,
        "h": 17,
        "rooms": [
            {"area": "Hall", "rects": [[5, 3, 4, 4]]},
            {"area": "Garden", "outside": True, "rects": [[0, 0, 3, 3]]},
            {"area": "Pool-Bereich (Süd)", "outside": True, "rects": [[0, 10, 4, 6]]},
        ],
        "hull": [[5, 3, 14, 9], [19, 6, 4, 6]],
        "layers": [{"n": 0, "x": -1.5, "y": 0, "w": 26, "rot": 12.5, "op": 0.4}, {"n": 2}],
    }
    floor, m = hm.validate_map(body, fa)
    assert [r.get("outside", False) for r in m["rooms"]] == [False, True, True]
    assert m["hull"][1] == [19, 6, 4, 6] and m["layers"][0]["rot"] == 12.5 and m["layers"][1]["w"] == 24
    assert hm.room_at(m, 1, 1) is None and hm.room_at(m, 6, 4) == "Hall"  # outside areas never count as a room
    assert hm.layer_key("ground_floor", 0) == "ground_floor" and hm.layer_key("ground_floor", 2) == "ground_floor_l2"


@pytest.mark.parametrize(
    "patch",
    [
        {"rooms": [{"area": "<b>x</b>", "outside": True, "rects": [[0, 0, 1, 1]]}]},
        {"rooms": [{"area": "Garden", "rects": [[0, 0, 1, 1]]}]},  # another floor's area only as outside area
        {"hull": [[0, 0, 1, 1]] * 41},
        {"layers": [{"n": 4}]},
        {"layers": [{"n": 0}, {"n": 0}]},
        {"layers": [{"n": 0, "rot": 400}]},
        {"layers": [{"n": 0, "op": 2}]},
        {"layers": [{"n": True}]},
    ],
)
def test_invalid_outside_hull_layers(patch):
    fa = {"Ground floor": ["Hall"], "Outside": ["Garden"]}
    with pytest.raises(ValueError):
        hm.validate_map({"floor": "Ground floor", "w": 12, "h": 10, "rooms": [], **patch}, fa)


def test_service_floorplan_layers(tmp_path):
    import base64

    from demo import build

    from bifrost_app.floorplan import PNG_MAGIC

    svc = build(str(tmp_path / "h.db"))
    floor = next(f for f in svc.live_view()["floors"] if f["areas"])["name"]
    img = base64.b64encode(PNG_MAGIC + b"0" * 20).decode()
    svc.set_floorplan({"floor": floor, "image": img})
    svc.set_floorplan({"floor": floor, "image": img, "layer": 2})
    plans = svc.live_view()["layouts"][floor]["plans"]
    assert [p["n"] for p in plans] == [0, 2]
    with pytest.raises(ValueError):
        svc.set_floorplan({"floor": floor, "image": img, "layer": 9})
    svc.delete_floorplan(floor, 2)
    assert [p["n"] for p in svc.live_view()["layouts"][floor]["plans"]] == [0]


def test_plan_existence_is_cached_and_versioned(tmp_path):
    import base64

    from demo import build

    from bifrost_app.floorplan import PNG_MAGIC

    svc = build(str(tmp_path / "h.db"))
    floor = next(f for f in svc.live_view()["floors"] if f["areas"])["name"]
    calls = []
    orig = svc.store.get_value
    svc.store.get_value = lambda k: (calls.append(k), orig(k))[1]
    svc.live_view()
    svc.live_view()
    assert sum(1 for k in calls if k.startswith("floorplan:")) == 0  # never reads the picture itself
    svc.store.get_value = orig
    svc.set_floorplan({"floor": floor, "image": base64.b64encode(PNG_MAGIC + b"0" * 20).decode(), "layer": 1})
    plan = svc.live_view()["layouts"][floor]["plans"][0]
    assert plan["n"] == 1 and plan["v"]


def test_own_mqtt_entities_are_not_new_sensors(tmp_path):
    from demo import build

    svc = build(str(tmp_path / "h.db"))
    orig = svc.client.registries

    def reg():
        r = orig()
        r["entities"].append({"entity_id": "binary_sensor.sofa_occupancy", "platform": "mqtt", "unique_id": "bifrost_zone_sofa_binary_sensor"})
        return r

    svc.client.registries = reg
    svc.client.states.append({"entity_id": "binary_sensor.sofa_occupancy", "state": "off", "attributes": {"device_class": "occupancy"}})
    svc.scan()
    assert "binary_sensor.sofa_occupancy" not in svc.snap.entities


def test_quarter_metre_grid_survives_saving():
    """Rooms drawn on the 0.25 m grid keep their edges (no rounding to 0.1 m)."""
    body = {
        "floor": "Ground floor",
        "w": 11,
        "h": 9,
        "rooms": [{"area": "Hall", "rects": [[0.25, 0.75, 3.25, 2.5]]}, {"area": "Kitchen", "rects": [[3.5, 0.75, 2.75, 2.5]]}],
        "devices": [{"id": "dev:shellyhall01", "kind": "scanner", "x": 1.25, "y": 8.75}],
    }
    _, m = hm.validate_map(body, FA)
    assert m["rooms"][0]["rects"] == [[0.25, 0.75, 3.25, 2.5]]
    assert m["rooms"][1]["rects"] == [[3.5, 0.75, 2.75, 2.5]]
    assert m["devices"][0]["x"] == 1.25 and m["devices"][0]["y"] == 8.75


def test_ha_room_can_be_shown_as_outside_area():
    """A room that is an HA area of this floor (e.g. a terrace) may be flagged outside: it stays the HA area, the map treats it as outside."""
    body = {"floor": "Ground floor", "w": 12, "h": 9, "rooms": [{"area": "Living", "rects": [[0, 0, 6, 3]], "outside": True}, {"area": "Hall", "rects": [[0, 3, 6, 6]]}]}
    _, m = hm.validate_map(body, FA)
    assert m["rooms"][0] == {"area": "Living", "rects": [[0, 0, 6, 3]], "outside": True}
    assert "outside" not in m["rooms"][1]
    assert hm.room_at(m, 3, 1) is None  # outside areas never count as a room inside
    assert hm.room_at(m, 3, 5) == "Hall"


def test_doors_and_windows_keep_their_direction():
    body = {"floor": "Ground floor", "w": 10, "h": 8, "marks": [{"kind": "door", "x": 0, "y": 3, "r": 90}, {"kind": "window", "x": 5, "y": 0}, {"kind": "window", "x": 5, "y": 8, "r": 0}]}
    _, m = hm.validate_map(body, FA)
    assert m["marks"][0]["r"] == 90 and "r" not in m["marks"][1] and "r" not in m["marks"][2]
    with pytest.raises(ValueError):
        hm.validate_map({**body, "marks": [{"kind": "door", "x": 0, "y": 3, "r": 30}]}, FA)
