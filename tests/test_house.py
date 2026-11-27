import base64
from datetime import UTC, datetime, timedelta

import pytest

from bifrost_app import house
from bifrost_app.floorplan import PNG_MAGIC
from bifrost_app.people import Person


def test_auto_layout_puts_walking_neighbours_next_to_each_other():
    paths = {"areas": ["Hall", "Kitchen", "Living", "Office"], "cells": [[{"n": 0}, {"n": 9}, {"n": 0}, {"n": 0}], [{"n": 9}, {"n": 0}, {"n": 0}, {"n": 0}], [{"n": 0}] * 4, [{"n": 0}] * 4]}
    cells = house.auto_layout(["Hall", "Kitchen", "Living", "Office"], paths)
    assert set(cells.values()) == {"Hall", "Kitchen", "Living", "Office"}
    assert all(0 <= int(k.split(",")[0]) < house.COLS and 0 <= int(k.split(",")[1]) < house.ROWS for k in cells)
    assert house.auto_layout([]) == {}


def test_layout_validation():
    fa = {"Ground floor": ["Hall", "Kitchen"]}
    floor, cells = house.validate_layout({"floor": "Ground floor", "areas": ["Hall"], "cells": [[0, 0, 0], [1, 0, 0]]}, fa)
    assert floor == "Ground floor" and cells == {"0,0": "Hall", "1,0": "Hall"}
    for bad in (
        {"floor": "Attic", "areas": [], "cells": []},
        {"floor": "Ground floor", "areas": ["Garage"], "cells": []},
        {"floor": "Ground floor", "areas": ["Hall"], "cells": [[99, 0, 0]]},
        {"floor": "Ground floor", "areas": ["Hall"], "cells": [[0, 0, 5]]},
        {"floor": "Ground floor", "areas": ["Hall"], "cells": [["0", 0, 0]]},
        {"floor": "Ground floor", "areas": ["Hall"], "cells": [[0, 0, 0]] * 900},
    ):
        with pytest.raises(ValueError):
            house.validate_layout(bad, fa)


def test_avatars_only_in_a_room_when_the_source_is_steady():
    now = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    a = Person("a", "A", trackers=["device_tracker.a", "sensor.a_area"])
    b = Person("b", "B", trackers=["device_tracker.b", "sensor.b_area"])
    c = Person("c", "C")
    states = {
        "sensor.a_area": {"state": "Kitchen", "last_changed": (now - timedelta(minutes=5)).isoformat()},
        "sensor.b_area": {"state": "Kitchen", "last_changed": (now - timedelta(seconds=30)).isoformat()},
        "device_tracker.b": {"state": "home"},
    }
    out = {x["id"]: x for x in house.avatars([a, b, c], {"a": ["sensor.a_area"], "b": ["sensor.b_area"]}, states, {"Kitchen"}, now)}
    assert out["a"]["place"] == "room" and out["a"]["area"] == "Kitchen"
    assert out["b"]["place"] == "house" and "c" not in out


def test_incident_groups_deviations_with_stages_and_score():
    t = datetime(2026, 3, 1, 3, 12, tzinfo=UTC)
    devs = [
        {"id": "d1", "kind": "unexplained", "key": "door", "facts": {"door": "binary_sensor.garage_door", "ts": t.isoformat()}, "ts": t.isoformat(), "status": "open"},
        {"id": "d2", "kind": "rare", "key": "x", "facts": {"sensor": "binary_sensor.garage_door", "ts": (t + timedelta(seconds=5)).isoformat(), "bits": 4}, "ts": t.isoformat(), "status": "open"},
    ]
    ev = [
        {"ts": (t - timedelta(seconds=9)).isoformat(), "entity_id": "binary_sensor.motion_outside_garage", "kind": "on", "state": "on"},
        {"ts": t.isoformat(), "entity_id": "binary_sensor.garage_door", "kind": "on", "state": "on"},
        {"ts": (t + timedelta(seconds=8)).isoformat(), "entity_id": "binary_sensor.motion_cloakroom", "kind": "on", "state": "on"},
    ]
    meta = {"binary_sensor.motion_outside_garage": {"category": "motion"}, "binary_sensor.motion_cloakroom": {"category": "motion"}, "binary_sensor.garage_door": {"category": "openings"}}
    sides = {"binary_sensor.motion_outside_garage": {"side": "outside"}, "binary_sensor.motion_cloakroom": {"side": "inside"}}
    inc = house.incidents(devs, ev, meta, sides, t + timedelta(hours=1))
    assert len(inc) == 1 and inc[0]["score"] >= 90 and inc[0]["kinds"] == ["rare", "unexplained"]
    st = {s["stage"]: s for s in inc[0]["stages"]}
    assert st["approach"]["ok"] and st["access"]["ok"] and st["inside"]["ok"] and not st["identity"]["ok"]


def test_pattern_entity_validation_and_slug():
    pid, on, slug = house.validate_pattern_entity({"id": "r1", "on": True, "slug": "leaving_morning"}, {"r1"}, {})
    assert (pid, on, slug) == ("r1", True, "leaving_morning")
    for bad in ({"id": "zz", "on": True}, {"id": "r1", "on": "yes"}, {"id": "r1", "on": True, "slug": "Bad Slug"}):
        with pytest.raises(ValueError):
            house.validate_pattern_entity(bad, {"r1"}, {})
    with pytest.raises(ValueError):
        house.validate_pattern_entity({"id": "r1", "on": True, "slug": "x"}, {"r1"}, {"x": "r2"})
    assert house.default_slug({"type": "block", "title": "Entry via Front door"}) == "block_entry_via_front_door"


def test_service_layout_floorplan_and_pattern_entities(tmp_path):
    from demo import build

    svc = build(str(tmp_path / "h.db"))
    v = svc.live_view()
    floor = next(f for f in v["floors"] if f["areas"])
    lay = v["layouts"][floor["name"]]
    assert lay["cells"] and not lay["saved"]
    areas = [a["name"] for a in floor["areas"]]
    svc.set_layout({"floor": floor["name"], "areas": areas[:1], "cells": [[0, 0, 0], [0, 1, 0]]})
    assert svc.live_view()["layouts"][floor["name"]]["saved"]
    svc.set_floorplan({"floor": floor["name"], "image": base64.b64encode(PNG_MAGIC + b"0" * 20).decode()})
    assert svc.live_view()["layouts"][floor["name"]]["plan"]
    svc.delete_floorplan(floor["name"])
    svc.reset_layout(floor["name"])
    assert not svc.live_view()["layouts"][floor["name"]]["saved"]
    items = svc.recognition_view()["items"]
    r = next(x for x in items if x["type"] == "routine")
    res = svc.set_pattern_entity({"id": r["id"], "on": True})
    svc.publish_pattern_entities(datetime.now(UTC))
    assert res["entity_id"] in svc.client.published
    assert svc.set_pattern_entity({"id": r["id"], "on": False}) == {"id": r["id"], "on": False}
    inc = svc.incidents_view()
    assert inc["items"] and "questions" in inc
