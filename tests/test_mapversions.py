"""0.18: house configuration with versions, a suggestion that never breaks anything, devices into their areas."""

import json
import math

import pytest

from bifrost_app import housemap as hm
from bifrost_app import mapversions as mv

ROOMS = [{"area": "Hall", "rects": [[0, 0, 4, 9]]}, {"area": "Kitchen", "rects": [[4, 0, 8, 4]]}]
FLOOR = {"w": 12, "h": 9, "rooms": ROOMS, "stairs": [], "marks": [], "devices": [], "hull": [], "layers": [], "zones": []}


def test_diff_counts_changes():
    new = json.loads(json.dumps(FLOOR))
    new["rooms"][0]["rects"] = [[0, 0, 4, 8]]
    new["rooms"].append({"area": "Living", "rects": [[4, 4, 8, 5]]})
    new["devices"] = [{"id": "dev:a", "kind": "scanner", "x": 1, "y": 1}]
    d = mv.diff(FLOOR, new)
    assert d == {"rooms_added": 1, "rooms_changed": 1, "devices_added": 1}
    moved = json.loads(json.dumps(new))
    moved["devices"][0]["x"] = 2
    assert mv.diff(new, moved) == {"devices_moved": 1}
    assert mv.diff(new, new) == {}


def test_add_missing_keeps_everything_that_exists():
    cur = json.loads(json.dumps(FLOOR))
    cur["devices"] = [{"id": "dev:a", "kind": "scanner", "x": 1, "y": 1}]
    cur["zones"] = [{"name": "Sofa", "rects": [[1, 1, 2, 2]]}]
    cur["marks"] = [{"kind": "door", "x": 0, "y": 2}]
    sug = {"rooms": [{"area": "Hall", "rects": [[0, 0, 6, 6]]}, {"area": "Living", "rects": [[0, 0, 6, 6]]}, {"area": "Bath", "rects": [[4, 4, 3, 3]]}]}
    out = mv.add_missing(cur, sug)
    for k in ("devices", "zones", "marks", "stairs", "hull", "layers"):
        assert out[k] == cur[k]
    assert out["rooms"][:2] == cur["rooms"]  # existing rooms unchanged
    added = {r["area"]: r["rects"] for r in out["rooms"][2:]}
    assert set(added) == {"Living", "Bath"}
    taken = [q for r in cur["rooms"] for q in r["rects"]]
    for rects in added.values():  # never on top of an existing room
        assert not any(mv._overlaps(q, t) for q in rects for t in taken)
    hm.validate_map({"floor": "Ground floor", **out}, {"Ground floor": ["Hall", "Kitchen", "Living", "Bath"]})


def test_place_puts_devices_into_their_room_without_overlap():
    m = json.loads(json.dumps(FLOOR))
    m["devices"] = [{"id": "binary_sensor.old", "kind": "sensor", "x": 6, "y": 2}]
    items = [{"id": f"binary_sensor.m{i}", "kind": "sensor", "area": "Kitchen", "name": f"M{i}"} for i in range(4)]
    items += [{"id": "binary_sensor.old", "kind": "sensor", "area": "Hall"}, {"id": "binary_sensor.x", "kind": "sensor", "area": None}, {"id": "binary_sensor.y", "kind": "sensor", "area": "Attic"}]
    res = mv.place(m, items)
    m2 = {**m, "devices": res["devices"]}
    where = hm.placed(m2)
    for i in range(4):
        assert where[f"binary_sensor.m{i}"]["area"] == "Kitchen"
    assert where["binary_sensor.old"]["x"] == 6  # already placed – stays
    pts = [(d["x"], d["y"]) for d in res["devices"]]
    assert all(math.hypot(a[0] - b[0], a[1] - b[1]) >= mv.SPACING - 1e-6 for i, a in enumerate(pts) for b in pts[i + 1 :])
    assert all(abs(v * 4 - round(v * 4)) < 1e-9 for p in pts for v in p)  # on the 0.25 m grid
    assert {c["id"]: c["reason"] for c in res["cannot"]} == {"binary_sensor.x": "no_area", "binary_sensor.y": "area_not_drawn"}
    # re-place on request
    res2 = mv.place(m, items[:0] + [{"id": "binary_sensor.old", "kind": "sensor", "area": "Hall"}], replace_placed=True)
    assert hm.placed({**m, "devices": res2["devices"]})["binary_sensor.old"]["area"] == "Hall"
    # contacts go to a wall of their room
    wall = mv.place(m, [{"id": "binary_sensor.door", "kind": "sensor", "area": "Kitchen"}], wall=True)
    d = next(x for x in wall["devices"] if x["id"] == "binary_sensor.door")
    assert d["x"] in (4, 12) or d["y"] in (0, 4)


def test_store_keeps_50_versions_and_pinned_ones():
    from bifrost_app.store import Store

    st = Store(":memory:")
    first = st.add_version("map", "eg", {"n": 0}, "save")
    st.pin_version("map", "eg", first, True, "Before the move")
    for i in range(1, 60):
        st.add_version("map", "eg", {"n": i}, "save", {"rooms_changed": 1})
    vs = st.list_versions("map", "eg")
    assert len([v for v in vs if not v["pinned"]]) == mv.KEEP
    assert vs[-1]["version"] == first and vs[-1]["pinned"] and vs[-1]["label"] == "Before the move"
    assert st.get_version("map", "eg", vs[0]["version"]) == {"n": 59}


def _svc(tmp_path):
    from demo import build

    return build(str(tmp_path / "v.db"))


def test_suggestion_never_deletes_and_restore_brings_back_exactly(tmp_path):
    svc = _svc(tmp_path)
    floor = "Ground floor"
    cur = svc._current_map(floor)
    drawn = {**cur, "rooms": cur["rooms"][:2], "zones": [{"name": "Desk", "rects": [[1, 1, 1, 1]]}]}
    svc.set_map({"floor": floor, **drawn})
    saved = svc.store.get_obj("map", "ground_floor") or svc.store.get_obj("map", next(iter(k for k in [__import__("bifrost_app.house", fromlist=["floor_key"]).floor_key(floor)])))
    # preview changes nothing
    p = svc.suggest_map({"floor": floor, "mode": "add"})
    assert p["preview"] and p["summary"].get("rooms_added", 0) >= 1
    key = __import__("bifrost_app.house", fromlist=["floor_key"]).floor_key(floor)
    assert svc.store.get_obj("map", key) == saved
    # add: existing rooms and zones stay
    r = svc.suggest_map({"floor": floor, "mode": "add", "preview": False})
    after = svc.store.get_obj("map", key)
    assert after["zones"] == drawn["zones"] and after["rooms"][:2] == saved["rooms"][:2]
    # replace: a version exists before, restore returns the old drawing exactly
    before_v = r["version"]
    svc.suggest_map({"floor": floor, "mode": "replace", "preview": False})
    assert svc.store.get_obj("map", key)["zones"] == []
    svc.restore_map({"floor": floor, "version": before_v})
    assert svc.store.get_obj("map", key) == after
    # the old destructive endpoint no longer deletes
    svc.reset_map(floor)
    assert svc.store.get_obj("map", key) is not None
    vs = svc.map_versions(floor)["versions"]
    assert [v["source"] for v in vs][:4] == ["suggestion", "restore", "suggestion", "suggestion"]


def test_place_devices_per_kind_and_export_import_round_trip(tmp_path):
    svc = _svc(tmp_path)
    floor = "Ground floor"
    pre = svc.place_devices({"floor": floor, "kind": "motion"})
    assert pre["preview"] and pre["placed"]
    key = __import__("bifrost_app.house", fromlist=["floor_key"]).floor_key(floor)
    done = svc.place_devices({"floor": floor, "kind": "motion", "preview": False})
    m = svc.store.get_obj("map", key)
    where = hm.placed(m)
    for p in done["placed"]:
        assert where[p["id"]]["area"] == p["area"]
    counts = svc.place_counts(floor)["kinds"]
    assert counts["motion"]["place"] == 0  # all placed now
    with pytest.raises(ValueError):
        svc.place_devices({"floor": floor, "kind": "rockets"})
    # export → import gives the same maps
    exp = svc.export_house()
    assert exp["kind"] == "house" and floor in exp["floors"]
    svc.set_map({"floor": floor, **{**m, "devices": []}})
    rep = svc.import_house(json.loads(json.dumps(exp)))
    assert floor in rep["floors"] and svc.store.get_obj("map", key)["devices"] == m["devices"]
    # unknown areas are reported and kept as outside areas
    bad = json.loads(json.dumps(exp))
    bad["floors"][floor]["map"]["rooms"].append({"area": "Old cellar", "rects": [[0, 0, 1, 1]]})
    rep = svc.import_house(bad)
    assert rep["unknown_areas"][floor] == ["Old cellar"]
    assert any(r["area"] == "Old cellar" and r.get("outside") for r in svc.store.get_obj("map", key)["rooms"])
    for broken in ({"kind": "other"}, {"kind": "house", "floors": {floor: {"map": {"rooms": "x"}}}}, {"kind": "house", "floors": {floor: {"map": m, "plans": {"0": "bm90IGFuIGltYWdl"}}}}):
        with pytest.raises(ValueError):
            svc.import_house(broken)
