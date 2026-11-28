"""0.19: doors and windows are contacts on the right wall; placed devices are named."""

import math

from bifrost_app import housemap as hm
from bifrost_app import mapversions as mv

# two rooms side by side, a third behind the first; everything else is outside
MAP = {
    "w": 10,
    "h": 8,
    "rooms": [
        {"area": "Hall", "rects": [[0, 0, 4, 4]]},
        {"area": "Living", "rects": [[4, 0, 6, 4]]},
        {"area": "Study", "rects": [[0, 4, 4, 4]]},
        {"area": "Terrace", "rects": [[4, 4, 6, 4]], "outside": True},
    ],
    "marks": [],
    "devices": [],
}


def test_contact_kind_from_device_class():
    assert mv.contact_kind("binary_sensor", "door") == "door"
    assert mv.contact_kind("binary_sensor", "window") == "window"
    assert mv.contact_kind("binary_sensor", "garage_door") == "garage_door"
    assert mv.contact_kind("binary_sensor", "opening") == "opening"
    assert mv.contact_kind("binary_sensor", None) == "opening"
    assert mv.contact_kind("cover", "garage") == "garage_door"


def test_walls_know_outer_and_inner_sides():
    ws = mv.walls(MAP, "Hall")
    inner = {w["neighbour"] for w in ws if not w["outer"]}
    assert inner == {"Living", "Study"}
    assert sum(w["length"] for w in ws) == 16  # the whole 4 × 4 outline
    outer = [w for w in ws if w["outer"]]
    assert {(w["x1"], w["x2"]) for w in outer if not w["vertical"]} == {(0, 4)} and any(w["vertical"] and w["x1"] == 0 for w in outer)
    # an outside area behind a wall counts as outside
    assert any(w["outer"] and w["y1"] == 4 for w in mv.walls(MAP, "Living"))


def test_contacts_go_to_the_right_wall_and_never_on_top_of_each_other():
    items = [
        {"id": "binary_sensor.hall_window", "area": "Hall", "contact": "window"},
        {"id": "binary_sensor.hall_window_2", "area": "Hall", "contact": "window"},
        {"id": "binary_sensor.front_door", "area": "Hall", "contact": "door"},
        {"id": "binary_sensor.hall_living_door", "area": "Hall", "contact": "door"},
        {"id": "binary_sensor.nowhere", "area": None, "contact": "door"},
    ]
    m = {**MAP, "devices": [{"id": "binary_sensor.hall_window", "kind": "sensor", "x": 2, "y": 2}]}
    res = mv.place_contacts(m, items, entrances={"binary_sensor.front_door"}, prefer={"Hall": ["Living"]})
    ws = mv.walls(MAP, "Hall")
    by = {k["entity_id"]: k for k in res["marks"]}

    def wall_of(k):
        return next(w for w in ws if min(w["x1"], w["x2"]) <= k["x"] <= max(w["x1"], w["x2"]) and min(w["y1"], w["y2"]) <= k["y"] <= max(w["y1"], w["y2"]))

    for wid in ("binary_sensor.hall_window", "binary_sensor.hall_window_2", "binary_sensor.front_door"):
        assert wall_of(by[wid])["outer"], wid  # windows and the entrance door on outer walls
    assert wall_of(by["binary_sensor.hall_living_door"])["neighbour"] == "Living"  # inner door towards the learned neighbour
    assert by["binary_sensor.hall_window"]["contact"] == "window" and by["binary_sensor.hall_window"]["kind"] == "window"
    assert by["binary_sensor.front_door"]["kind"] == "door"
    pts = [(k["x"], k["y"]) for k in res["marks"]]
    assert all(math.hypot(a[0] - b[0], a[1] - b[1]) >= mv.SPACING - 1e-6 for i, a in enumerate(pts) for b in pts[i + 1 :])
    for k in res["marks"]:  # vertical walls give vertical marks
        assert (k.get("r") == 90) == wall_of(k)["vertical"]
    assert not res["devices"]  # a contact is never a free device any more
    assert [c["reason"] for c in res["cannot"]] == ["no_area"]
    hm.validate_map({"floor": "EG", **{**m, "marks": res["marks"], "devices": res["devices"]}}, {"EG": ["Hall", "Living", "Study"]})


def test_old_placed_contacts_become_contacts_on_walls_and_are_named(tmp_path):
    from demo import build

    svc = build(str(tmp_path / "c.db"))
    floor = next(f for f, areas in svc._floor_areas().items() if "Living" in areas)
    cur = svc._current_map(floor)
    win = "binary_sensor.living_window_garden"
    svc.update_entity(win, "included", "openings", None)
    svc.set_map({"floor": floor, **{**cur, "devices": [{"id": win, "kind": "sensor", "x": 1, "y": 1}]}})
    v = svc.live_view()  # migrates on load
    lay = v["layouts"][floor]["map"]
    assert not any(d["id"] == win for d in lay["devices"])
    mark = next(k for k in lay["marks"] if k.get("entity_id") == win)
    assert mark["contact"] == "window" and mark["kind"] == "window"
    assert svc.map_versions(floor)["versions"][0]["source"] == "migrate"
    info = v["devinfo"][win]
    assert info["entity"] == win and info["kind"] == "window" and info["area"] == "Living" and info["name"]
    # placing "doors & windows" later puts them as contacts, not devices
    res = svc.place_devices({"floor": floor, "kind": "openings"})
    assert all("contact" in k for k in res["marks"] if k.get("entity_id"))
