"""House configuration with versions (0.18): what changed, a suggestion that only adds, devices into their areas.

Pure functions – storage is in ``store.Store`` (table ``map_versions``), the endpoints in ``service``.
"""

from __future__ import annotations

import math

KEEP = 50  # versions per floor (pinned ones are kept on top)
SOURCES = ("save", "suggestion", "auto_place", "import", "restore", "before", "migrate")
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


# --- 0.19: doors and windows are contacts on a wall --------------------------------------------------
CONTACT_KINDS = ("door", "garage_door", "window", "opening")
OUTER_ONLY = ("window", "garage_door")


def contact_kind(domain: str, device_class: str | None) -> str:
    """door / garage_door / window / opening from Home Assistant's device_class."""
    dc = (device_class or "").lower()
    if domain == "cover":
        return "garage_door" if dc in ("garage", "gate") else "opening"
    return dc if dc in ("door", "garage_door", "window") else "opening"


def walls(m: dict, area: str) -> list[dict]:
    """Wall segments of a room (union of its rectangles): each is outer (nothing or an outside area behind it) or
    inner with the neighbour room behind it. {x1, y1, x2, y2, outer, neighbour, vertical, length}"""
    rooms = [r for r in m.get("rooms", []) if r.get("rects")]
    mine = next((r for r in rooms if r["area"] == area), None)
    if not mine:
        return []
    xs = sorted({round(v, 3) for r in rooms for q in r["rects"] for v in (q[0], q[0] + q[2])})
    ys = sorted({round(v, 3) for r in rooms for q in r["rects"] for v in (q[1], q[1] + q[3])})

    def owner(cx: float, cy: float) -> str | None:
        for r in rooms:
            if r.get("outside"):
                continue
            if any(q[0] < cx < q[0] + q[2] and q[1] < cy < q[1] + q[3] for q in r["rects"]):
                return r["area"]
        return None

    def inside(cx: float, cy: float) -> bool:
        return any(q[0] < cx < q[0] + q[2] and q[1] < cy < q[1] + q[3] for q in mine["rects"])

    edges: list[tuple] = []  # (vertical, fixed coordinate, start, end, neighbour)
    for i in range(len(xs) - 1):
        for j in range(len(ys) - 1):
            cx, cy = (xs[i] + xs[i + 1]) / 2, (ys[j] + ys[j + 1]) / 2
            if not inside(cx, cy):
                continue
            dx, dy = (xs[i + 1] - xs[i]) / 2, (ys[j + 1] - ys[j]) / 2
            for nx, ny, vert, fixed, a, b in (
                (cx - 2 * dx, cy, True, xs[i], ys[j], ys[j + 1]),
                (cx + 2 * dx, cy, True, xs[i + 1], ys[j], ys[j + 1]),
                (cx, cy - 2 * dy, False, ys[j], xs[i], xs[i + 1]),
                (cx, cy + 2 * dy, False, ys[j + 1], xs[i], xs[i + 1]),
            ):
                if inside(nx, ny):
                    continue
                edges.append((vert, fixed, a, b, owner(nx, ny)))
    edges.sort(key=lambda e: (e[0], e[1], e[4] or "", e[2]))
    out: list[dict] = []
    for vert, fixed, a, b, nb in edges:  # join touching edges with the same neighbour into one wall
        last = out[-1] if out else None
        if last and last["vertical"] == vert and last["_fixed"] == fixed and last["neighbour"] == nb and abs(last["_b"] - a) < 1e-6:
            last["_b"] = b
        else:
            out.append({"vertical": vert, "_fixed": fixed, "_a": a, "_b": b, "neighbour": nb})
    res = []
    for w in out:
        if w["vertical"]:
            x1 = x2 = w["_fixed"]
            y1, y2 = w["_a"], w["_b"]
        else:
            y1 = y2 = w["_fixed"]
            x1, x2 = w["_a"], w["_b"]
        res.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2, "outer": w["neighbour"] is None, "neighbour": w["neighbour"], "vertical": w["vertical"], "length": round(abs(x2 - x1) + abs(y2 - y1), 3)})
    return res


def _slots(w: dict, taken: list[tuple[float, float]]) -> tuple[float, float] | None:
    """A free point on a wall, SPACING from its ends and from other contacts, on the grid."""
    n = int((w["length"] - SPACING) // SPACING)
    cands = [SPACING + i * SPACING for i in range(max(0, n))] or ([w["length"] / 2] if w["length"] >= GRID * 2 else [])
    mid = w["length"] / 2
    for off in sorted(cands, key=lambda o: abs(o - mid)):
        p = (w["x1"], _snap(w["y1"] + off)) if w["vertical"] else (_snap(w["x1"] + off), w["y1"])
        if all(math.hypot(p[0] - q[0], p[1] - q[1]) >= SPACING - 1e-6 for q in taken):
            return p
    return None


def place_contacts(m: dict, items: list[dict], entrances: set[str] | None = None, prefer: dict[str, list[str]] | None = None, replace_placed: bool = False) -> dict:
    """Door/window contacts as marks on the right wall of their room.

    items: [{id, area, contact, name}]. Windows and garage doors only on outer walls; entrance doors outer, other doors
    inner (preferring the neighbour with learned paths), else outer. Contacts of one room are spread over walls, ≥ 0.75 m
    apart. Returns {"marks", "devices", "placed", "cannot"} – devices no longer hold contacts."""
    entrances, prefer = entrances or set(), prefer or {}
    ids = {it["id"] for it in items}
    marks = [dict(k) for k in m.get("marks", []) if not (replace_placed and k.get("entity_id") in ids)]
    have = {k.get("entity_id") for k in marks if k.get("entity_id")}
    devices = [d for d in m.get("devices", []) if d["id"] not in ids]  # a contact is a mark, never a free device
    rooms = {r["area"] for r in m.get("rooms", [])}
    placed, cannot = [], []
    used_walls: dict[str, list[int]] = {}
    for it in items:
        if it["id"] in have:
            continue
        if not it.get("area"):
            cannot.append({"id": it["id"], "name": it.get("name") or it["id"], "reason": "no_area"})
            continue
        if it["area"] not in rooms:
            cannot.append({"id": it["id"], "name": it.get("name") or it["id"], "reason": "area_not_drawn"})
            continue
        ws = walls(m, it["area"])
        kind = it.get("contact") or "opening"
        outer = [i for i, w in enumerate(ws) if w["outer"]]
        inner = [i for i, w in enumerate(ws) if not w["outer"]]
        if kind in OUTER_ONLY or it["id"] in entrances:
            first, check = outer, not outer
        elif kind == "door":
            pref = prefer.get(it["area"], [])
            inner.sort(key=lambda i: (pref.index(ws[i]["neighbour"]) if ws[i]["neighbour"] in pref else len(pref), -ws[i]["length"]))
            first, check = inner or outer, False
        else:
            first, check = outer + inner, False
        order = first + [i for i in range(len(ws)) if i not in first]
        seen = used_walls.setdefault(it["area"], [])
        order.sort(key=lambda i: (i not in first, seen.count(i)))  # spread over walls before doubling up
        taken = [(k["x"], k["y"]) for k in marks]
        spot = None
        for i in order:
            spot = _slots(ws[i], taken)
            if spot:
                wi = i
                break
        if not spot:
            cannot.append({"id": it["id"], "name": it.get("name") or it["id"], "reason": "room_full"})
            continue
        seen.append(wi)
        mk = {"kind": "window" if kind == "window" else "door", "x": spot[0], "y": spot[1], "entity_id": it["id"], "contact": kind}
        if ws[wi]["vertical"]:
            mk["r"] = 90
        marks.append(mk)
        have.add(it["id"])
        placed.append(
            {
                "id": it["id"],
                "name": it.get("name") or it["id"],
                "area": it["area"],
                "x": spot[0],
                "y": spot[1],
                "contact": kind,
                "wall": "outer" if ws[wi]["outer"] else "inner",
                "check": check or (kind in OUTER_ONLY and not ws[wi]["outer"]),
            }
        )
    return {"marks": marks, "devices": devices, "placed": placed, "cannot": cannot}
