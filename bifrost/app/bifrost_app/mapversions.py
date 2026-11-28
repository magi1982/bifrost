"""House configuration with versions (0.18): what changed, a suggestion that only adds, devices into their areas.

Pure functions – storage is in ``store.Store`` (table ``map_versions``), the endpoints in ``service``.
"""

from __future__ import annotations

import math

KEEP = 50  # versions per floor (pinned ones are kept on top)
SOURCES = ("save", "suggestion", "auto_place", "import", "restore", "before")
GRID = 0.25  # m – the drawing grid
EDGE = 0.5  # m – distance of a placed device from the room's edge
SPACING = 0.75  # m – placed devices are at least this far apart


def _rects(m: dict, key: str) -> list:
    return [list(map(float, r)) for r in m.get(key) or []]


def diff(old: dict | None, new: dict) -> dict:
    """Short summary of what changed between two maps of one floor (counts only, no names)."""
    old = old or {}
    o_rooms = {r["area"]: r for r in old.get("rooms", [])}
    n_rooms = {r["area"]: r for r in new.get("rooms", [])}
    o_dev = {d["id"]: d for d in old.get("devices", [])}
    n_dev = {d["id"]: d for d in new.get("devices", [])}
    o_z = {z["name"]: z for z in old.get("zones", [])}
    n_z = {z["name"]: z for z in new.get("zones", [])}
    out = {
        "rooms_added": len(n_rooms.keys() - o_rooms.keys()),
        "rooms_removed": len(o_rooms.keys() - n_rooms.keys()),
        "rooms_changed": sum(1 for a in n_rooms.keys() & o_rooms.keys() if n_rooms[a].get("rects") != o_rooms[a].get("rects") or bool(n_rooms[a].get("outside")) != bool(o_rooms[a].get("outside"))),
        "devices_added": len(n_dev.keys() - o_dev.keys()),
        "devices_removed": len(o_dev.keys() - n_dev.keys()),
        "devices_moved": sum(1 for i in n_dev.keys() & o_dev.keys() if (n_dev[i]["x"], n_dev[i]["y"]) != (o_dev[i]["x"], o_dev[i]["y"])),
        "zones_changed": len(n_z.keys() ^ o_z.keys()) + sum(1 for k in n_z.keys() & o_z.keys() if n_z[k].get("rects") != o_z[k].get("rects")),
        "marks_changed": int(old.get("marks", []) != new.get("marks", [])),
        "shape_changed": int(_rects(old, "hull") != _rects(new, "hull") or _rects(old, "stairs") != _rects(new, "stairs") or (old.get("w"), old.get("h")) != (new.get("w"), new.get("h"))),
        "plans_changed": int(old.get("layers", []) != new.get("layers", [])),
    }
    return {k: v for k, v in out.items() if v}


def _overlaps(a: list, b: list) -> bool:
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def add_missing(current: dict, suggestion: dict) -> dict:
    """Only add rooms that are not drawn yet; everything that exists stays exactly as it is.

    A suggested room goes to its suggested place if that is free; otherwise into a row below the drawing
    (the floor grows; the owner moves it later)."""
    out = {**current, "rooms": [dict(r) for r in current.get("rooms", [])]}
    taken = [q for r in out["rooms"] for q in r["rects"]] + _rects(out, "stairs")
    have = {r["area"] for r in out["rooms"]}
    below = float(out.get("h", 0))
    x_next = 0.0
    for r in suggestion.get("rooms", []):
        if r["area"] in have:
            continue
        rects = [list(map(float, q)) for q in r["rects"]]
        if any(_overlaps(q, t) for q in rects for t in taken):
            bw = max(q[0] + q[2] for q in rects) - min(q[0] for q in rects)
            bh = max(q[1] + q[3] for q in rects) - min(q[1] for q in rects)
            ox, oy = min(q[0] for q in rects), min(q[1] for q in rects)
            if x_next + bw > float(out.get("w", 0)):
                x_next = 0.0
                below = max(below, max((t[1] + t[3] for t in taken), default=0.0))
            rects = [[q[0] - ox + x_next, q[1] - oy + below, q[2], q[3]] for q in rects]
            x_next += bw
            out["h"] = round(max(float(out.get("h", 0)), below + bh), 2)
            out["w"] = round(max(float(out.get("w", 0)), max(q[0] + q[2] for q in rects)), 2)
        out["rooms"].append({"area": r["area"], "rects": rects})
        taken += rects
        have.add(r["area"])
    out["h"] = min(float(out.get("h", 0)), 80.0)
    return out


def _snap(v: float) -> float:
    return round(round(v / GRID) * GRID, 2)


def _spots(rect: list, n: int, used: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Free spots on the grid inside a rectangle, away from its edge and from devices already there."""
    x, y, w, h = rect
    e = min(EDGE, w / 4, h / 4)
    xs = [_snap(x + e + i * SPACING) for i in range(int(max(0, w - 2 * e) // SPACING) + 1)]
    ys = [_snap(y + e + j * SPACING) for j in range(int(max(0, h - 2 * e) // SPACING) + 1)]
    cx, cy = x + w / 2, y + h / 2
    cand = sorted(((px, py) for py in ys for px in xs), key=lambda p: math.hypot(p[0] - cx, p[1] - cy))
    out: list[tuple[float, float]] = []
    for p in cand:
        if all(math.hypot(p[0] - q[0], p[1] - q[1]) >= SPACING - 1e-6 for q in used + out):
            out.append(p)
            if len(out) == n:
                break
    return out


def _nearest_wall(rect: list, near: tuple[float, float]) -> tuple[float, float]:
    x, y, w, h = rect
    px, py = near
    opts = [(px, y), (px, y + h), (x, py), (x + w, py)]
    return min(opts, key=lambda p: math.hypot(p[0] - px, p[1] - py))


def place(m: dict, items: list[dict], replace_placed: bool = False, wall: bool = False) -> dict:
    """Put devices into the room of their HA area. items: [{id, kind, area, name}].

    Returns {"devices": new device list, "placed": [...], "cannot": [{id, name, reason}]}. Devices already on the map
    stay where they are unless replace_placed. ``wall``: doors/windows contacts sit on the nearest wall."""
    rooms = {r["area"]: r for r in m.get("rooms", [])}
    devices = [dict(d) for d in m.get("devices", [])]
    have = {d["id"] for d in devices}
    placed, cannot = [], []
    todo: dict[str, list[dict]] = {}
    for it in items:
        if it["id"] in have and not replace_placed:
            continue
        if not it.get("area"):
            cannot.append({"id": it["id"], "name": it.get("name") or it["id"], "reason": "no_area"})
            continue
        if it["area"] not in rooms:
            cannot.append({"id": it["id"], "name": it.get("name") or it["id"], "reason": "area_not_drawn"})
            continue
        todo.setdefault(it["area"], []).append(it)
    for area, its in todo.items():
        rect = max(rooms[area]["rects"], key=lambda q: q[2] * q[3])
        others = [d for d in devices if d["id"] not in {i["id"] for i in its}]
        used = [(d["x"], d["y"]) for d in others]
        spots = _spots(list(map(float, rect)), len(its), used)
        for i, it in enumerate(its):
            if i >= len(spots):
                cannot.append({"id": it["id"], "name": it.get("name") or it["id"], "reason": "room_full"})
                continue
            p = _nearest_wall(list(map(float, rect)), spots[i]) if wall else spots[i]
            p = (_snap(p[0]), _snap(p[1]))
            devices = [d for d in devices if d["id"] != it["id"]] + [{"id": it["id"], "kind": it["kind"], "x": p[0], "y": p[1]}]
            used.append(p)
            placed.append({"id": it["id"], "name": it.get("name") or it["id"], "area": area, "x": p[0], "y": p[1]})
    return {"devices": devices, "placed": placed, "cannot": cannot}
