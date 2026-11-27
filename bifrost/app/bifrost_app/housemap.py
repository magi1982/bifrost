"""House map 2.0 (0.11) – rooms drawn as rectangles in metres, stairs, doors/windows and placed devices.

One map per floor. Everything is in metres from the floor's top-left corner (0.1 m precision):

* rooms – an HA area made of one or more rectangles (an L-shaped hall is two touching rectangles);
* stairs – rectangles that connect this floor with the one above or below;
* marks – doors and windows as points on a wall, optionally bound to a sensor;
* devices – Bluetooth scanners (Shellys …), sensors and Bluetooth devices placed exactly; used later for
  positions (fingerprints / triangulation) and drawn on the live map.

The old 36×24 cell layout (0.9) is converted once into rectangles (one cell = 0.5 m).
"""

from __future__ import annotations

import re

MIN_SIZE, MAX_SIZE = 2.0, 80.0  # floor width/height in metres
DEFAULT_W, DEFAULT_H = 18.0, 12.0
CELL_M = 0.5  # one cell of the 0.9 grid
MAX_RECTS = 240
MAX_MARKS = 120
MAX_DEVICES = 240
MARK_KINDS = ("door", "window")
MAX_HULL = 40
MAX_ZONES = 30
MAX_LAYERS = 4  # floor plan pictures per floor
OUTSIDE_NAME = re.compile(r"^[\w äöüÄÖÜéèàçÉÈÀß.,'()&/+-]{1,40}$")
DEVICE_KINDS = ("scanner", "sensor", "ble")
_ID = re.compile(r"^(?:[a-z_]+\.[a-z0-9_]+|dev:[A-Za-z0-9_-]{1,64}|ble:[0-9A-F:]{2,40})$")


def _num(v: object, lo: float, hi: float, what: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:  # noqa: PLR0124 (NaN check)
        raise ValueError(f"{what}: number expected")
    if not lo <= v <= hi:
        raise ValueError(f"{what}: out of range")
    return round(float(v), 1)


def _rect(r: object, w: float, h: float) -> list[float]:
    if not (isinstance(r, list) and len(r) == 4):
        raise ValueError("rectangle: [x, y, w, h]")
    x, y = _num(r[0], 0, w, "x"), _num(r[1], 0, h, "y")
    rw, rh = _num(r[2], 0.1, w, "width"), _num(r[3], 0.1, h, "height")
    if x + rw > w + 0.05 or y + rh > h + 0.05:
        raise ValueError("rectangle outside the floor")
    return [x, y, rw, rh]


def validate_map(body: object, floor_areas: dict[str, list[str]]) -> tuple[str, dict]:  # noqa: C901
    """Check a map sent by the UI. Raises ValueError with a short reason.

    Inside rooms must be HA areas of this floor. Outside areas (terrace, pool …) may be any HA area or a free name.
    """
    if not isinstance(body, dict):
        raise ValueError("invalid body")
    floor = body.get("floor")
    if not isinstance(floor, str) or floor not in floor_areas:
        raise ValueError("unknown floor")
    w, h = _num(body.get("w", DEFAULT_W), MIN_SIZE, MAX_SIZE, "floor width"), _num(body.get("h", DEFAULT_H), MIN_SIZE, MAX_SIZE, "floor height")
    rooms_in, stairs_in = body.get("rooms") or [], body.get("stairs") or []
    marks_in, devs_in = body.get("marks") or [], body.get("devices") or []
    hull_in, layers_in, zones_in = body.get("hull") or [], body.get("layers") or [], body.get("zones") or []
    if not all(isinstance(x, list) for x in (rooms_in, stairs_in, marks_in, devs_in, hull_in, layers_in, zones_in)):
        raise ValueError("rooms, stairs, marks, devices, hull and layers must be lists")
    all_areas = {a for v in floor_areas.values() for a in v}
    rooms: list[dict] = []
    seen: set[str] = set()
    n = 0
    for r in rooms_in:
        outside = isinstance(r, dict) and r.get("outside") is True
        name = r.get("area") if isinstance(r, dict) else None
        ok = isinstance(name, str) and (name in floor_areas[floor] or (outside and (name in all_areas or OUTSIDE_NAME.match(name))))
        if not ok or name in seen:
            raise ValueError("unknown or duplicate area")
        rects = r.get("rects")
        if not isinstance(rects, list) or not rects:
            raise ValueError("room without rectangles")
        n += len(rects)
        if n > MAX_RECTS:
            raise ValueError(f"at most {MAX_RECTS} rectangles")
        seen.add(r["area"])
        room = {"area": r["area"], "rects": [_rect(x, w, h) for x in rects]}
        if outside:
            room["outside"] = True
        rooms.append(room)
    if n + len(stairs_in) > MAX_RECTS:
        raise ValueError(f"at most {MAX_RECTS} rectangles")
    stairs = [_rect(x, w, h) for x in stairs_in]
    if len(hull_in) > MAX_HULL:
        raise ValueError(f"at most {MAX_HULL} hull rectangles")
    hull = [_rect(x, w, h) for x in hull_in]
    if len(zones_in) > MAX_ZONES:
        raise ValueError(f"at most {MAX_ZONES} zones")
    zones, znames = [], set()
    for z in zones_in:
        if not isinstance(z, dict) or not isinstance(z.get("name"), str) or not OUTSIDE_NAME.match(z["name"]) or z["name"] in znames:
            raise ValueError("zone: unique name (letters, digits, max. 40)")
        rects = z.get("rects")
        if not isinstance(rects, list) or not 1 <= len(rects) <= 8:
            raise ValueError("zone: 1–8 rectangles")
        znames.add(z["name"])
        zones.append({"name": z["name"], "rects": [_rect(x, w, h) for x in rects]})
    if len(layers_in) > MAX_LAYERS:
        raise ValueError(f"at most {MAX_LAYERS} floor plan pictures")
    layers, nums = [], set()
    for lay in layers_in:
        if not isinstance(lay, dict) or not isinstance(lay.get("n"), int) or isinstance(lay.get("n"), bool) or not 0 <= lay["n"] < MAX_LAYERS or lay["n"] in nums:
            raise ValueError("layer: n 0..3, once")
        nums.add(lay["n"])
        layers.append(
            {
                "n": lay["n"],
                "x": _num(lay.get("x", 0), -MAX_SIZE, MAX_SIZE, "x"),
                "y": _num(lay.get("y", 0), -MAX_SIZE, MAX_SIZE, "y"),
                "w": _num(lay.get("w", w), 0.5, 4 * MAX_SIZE, "width"),
                "rot": _num(lay.get("rot", 0), -180, 180, "rotation"),
                "op": _num(lay.get("op", 0.5), 0, 1, "opacity"),
            }
        )
    if len(marks_in) > MAX_MARKS:
        raise ValueError(f"at most {MAX_MARKS} doors and windows")
    marks = []
    for m in marks_in:
        if not isinstance(m, dict) or m.get("kind") not in MARK_KINDS:
            raise ValueError("mark: door or window")
        item = {"kind": m["kind"], "x": _num(m.get("x"), 0, w, "x"), "y": _num(m.get("y"), 0, h, "y")}
        eid = m.get("entity_id")
        if eid is not None:
            if not isinstance(eid, str) or len(eid) > 120 or not _ID.match(eid):
                raise ValueError("invalid entity id")
            item["entity_id"] = eid
        marks.append(item)
    if len(devs_in) > MAX_DEVICES:
        raise ValueError(f"at most {MAX_DEVICES} devices")
    devices, ids = [], set()
    for d in devs_in:
        if not isinstance(d, dict) or d.get("kind") not in DEVICE_KINDS:
            raise ValueError("device: scanner, sensor or ble")
        did = d.get("id")
        if not isinstance(did, str) or len(did) > 120 or not _ID.match(did) or did in ids:
            raise ValueError("invalid or duplicate device id")
        ids.add(did)
        devices.append({"id": did, "kind": d["kind"], "x": _num(d.get("x"), 0, w, "x"), "y": _num(d.get("y"), 0, h, "y")})
    return floor, {"w": w, "h": h, "rooms": rooms, "stairs": stairs, "marks": marks, "devices": devices, "hull": hull, "layers": layers, "zones": zones}


def from_cells(cells: dict[str, str], cols: int = 36, rows: int = 24) -> dict:
    """Convert the 0.9 cell layout into rectangles (greedy: widest run, then grow downwards)."""
    left = {k: v for k, v in cells.items()}
    by_area: dict[str, list[list[float]]] = {}
    for y in range(rows):
        for x in range(cols):
            a = left.get(f"{x},{y}")
            if not a:
                continue
            x2 = x
            while left.get(f"{x2 + 1},{y}") == a:
                x2 += 1
            y2 = y
            while y2 + 1 < rows and all(left.get(f"{i},{y2 + 1}") == a for i in range(x, x2 + 1)):
                y2 += 1
            for j in range(y, y2 + 1):
                for i in range(x, x2 + 1):
                    left.pop(f"{i},{j}", None)
            by_area.setdefault(a, []).append([x * CELL_M, y * CELL_M, (x2 - x + 1) * CELL_M, (y2 - y + 1) * CELL_M])
    return {"w": cols * CELL_M, "h": rows * CELL_M, "rooms": [{"area": a, "rects": r} for a, r in by_area.items()], "stairs": [], "marks": [], "devices": [], "hull": [], "layers": [], "zones": []}


def room_at(m: dict, x: float, y: float) -> str | None:
    """The area a point lies in (stairs and outside → None)."""
    for r in m.get("rooms", []):
        if r.get("outside"):
            continue
        for rx, ry, rw, rh in r["rects"]:
            if rx <= x <= rx + rw and ry <= y <= ry + rh:
                return r["area"]
    return None


def placed(m: dict) -> dict[str, dict]:
    """Placed devices by id, each with its room."""
    return {d["id"]: {**d, "area": room_at(m, d["x"], d["y"])} for d in m.get("devices", [])}


SCANNER_MAKERS = re.compile(r"shelly|espressif|esphome|athom|olimex", re.I)


def scanner_candidates(devices: list[dict], entity_platforms: dict[str, set[str]], areas: dict[str, str]) -> list[dict]:
    """HA devices that can listen to Bluetooth (Shelly Gen2+, ESPHome proxies …), for placing on the map."""
    out = []
    for d in devices:
        did = d.get("id")
        if not did or d.get("disabled_by") or d.get("entry_type") == "service":
            continue
        plats = entity_platforms.get(did, set())
        conns = {c[0] for c in d.get("connections") or [] if isinstance(c, (list, tuple)) and c}
        if not (SCANNER_MAKERS.search(f"{d.get('manufacturer') or ''} {d.get('model') or ''}") or plats & {"shelly", "esphome"} or "bluetooth" in conns):
            continue
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", did):
            continue
        name = d.get("name_by_user") or d.get("name") or did
        macs = [str(c[1]) for c in d.get("connections") or [] if isinstance(c, (list, tuple)) and len(c) == 2 and c[0] in ("mac", "bluetooth")]
        out.append({"id": f"dev:{did}", "name": name, "model": d.get("model") or "", "manufacturer": d.get("manufacturer") or "", "area": areas.get(d.get("area_id") or ""), "macs": macs})
    return sorted(out, key=lambda x: (x["area"] or "~", x["name"]))


def clean(m: dict, areas: list[str]) -> dict:
    """A stored map for display: rooms whose HA area was deleted or moved to another floor are dropped."""
    return {
        "w": m.get("w", DEFAULT_W),
        "h": m.get("h", DEFAULT_H),
        "rooms": [r for r in m.get("rooms", []) if r.get("outside") or r.get("area") in areas],
        "stairs": m.get("stairs", []),
        "marks": m.get("marks", []),
        "devices": m.get("devices", []),
        "hull": m.get("hull", []),
        "layers": m.get("layers", []),
        "zones": m.get("zones", []),
    }


def layer_key(floor_key: str, n: int) -> str:
    """Store key of a floor plan picture: layer 0 keeps the 0.9 key, more layers get a suffix."""
    return floor_key if n == 0 else f"{floor_key[:37]}_l{n}"
