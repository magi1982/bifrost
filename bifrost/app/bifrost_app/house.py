"""House tiles, incidents and pattern entities (0.9) – the control-room views.

* **Layout**: per Home Assistant floor every area becomes a room on a fine grid (36 × 24 cells). Without a
  saved layout Bifrost suggests one, neighbours (learned walks) next to each other. The owner paints cells
  to give rooms any shape. Only counters and cell lists are stored.
* **Incidents** bundle deviations that belong together (within 10 minutes) into one chain with stages –
  approach → access → inside → identity – and a score, like an attack chain in security monitoring.
* **Pattern entities**: the owner switches single patterns on as Home Assistant entities, under a stable
  slug that survives re-learning. Information only – they never feed "empty confirmed".
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta

COLS, ROWS = 36, 24
MAX_CELLS = COLS * ROWS
SLUG_RE = re.compile(r"^[a-z0-9_]{1,40}$")
MAX_PATTERN_ENTITIES = 30
PULSE = timedelta(seconds=60)
GROUP = timedelta(minutes=10)
KIND_SCORE = {"unexplained": 60, "contradiction": 50, "rare": 20, "expected_missing": 15}
APPROACH, ACCESS, INSIDE, IDENTITY = "approach", "access", "inside", "identity"


# --- layout ----------------------------------------------------------------------------------
def auto_layout(areas: list[str], paths: dict | None = None) -> dict[str, str]:
    """Blocks on the grid, ordered so that areas people walk between sit next to each other."""
    if not areas:
        return {}
    paths = paths or {}
    pa, cells = paths.get("areas", []), paths.get("cells", [])
    weight: dict[tuple[str, str], int] = {}
    for i, a in enumerate(pa):
        for j, b in enumerate(pa):
            n = (cells[i][j] or {}).get("n", 0) if i < len(cells) and j < len(cells[i]) else 0
            if n and a != b:
                key = (a, b) if a < b else (b, a)
                weight[key] = weight.get(key, 0) + n
    order: list[str] = []
    left = sorted(areas, key=lambda a: -sum(n for k, n in weight.items() if a in k))
    while left:
        if not order:
            nxt = left[0]
        else:
            last = order[-1]
            nxt = max(left, key=lambda a: (weight.get((a, last) if a < last else (last, a), 0), -left.index(a)))
        order.append(nxt)
        left.remove(nxt)
    n = len(order)
    cols = math.ceil(math.sqrt(n * COLS / ROWS))
    rows = math.ceil(n / cols)
    bw, bh = COLS // cols, ROWS // rows
    out: dict[str, str] = {}
    for idx, a in enumerate(order):
        r, c = divmod(idx, cols)
        if r % 2:
            c = cols - 1 - c  # snake order keeps neighbours adjacent across rows
        for x in range(c * bw, c * bw + bw):
            for y in range(r * bh, r * bh + bh):
                out[f"{x},{y}"] = a
    return out


def validate_layout(body: object, floor_areas: dict[str, list[str]]) -> tuple[str, dict[str, str]]:
    """{"floor": str, "areas": [names], "cells": [[x, y, area_index], ...]} → (floor, {"x,y": area})."""
    if not isinstance(body, dict):
        raise ValueError("invalid body")
    floor = body.get("floor")
    if not isinstance(floor, str) or floor not in floor_areas:
        raise ValueError("unknown floor")
    names = body.get("areas")
    if not isinstance(names, list) or len(names) > 60 or any(not isinstance(a, str) or a not in floor_areas[floor] for a in names):
        raise ValueError("unknown area")
    cells = body.get("cells")
    if not isinstance(cells, list) or len(cells) > MAX_CELLS:
        raise ValueError("cells: list of at most 864")
    out: dict[str, str] = {}
    for c in cells:
        if not (isinstance(c, list) and len(c) == 3 and all(isinstance(v, int) and not isinstance(v, bool) for v in c)):
            raise ValueError("cell: [x, y, area]")
        x, y, i = c
        if not (0 <= x < COLS and 0 <= y < ROWS and 0 <= i < len(names)):
            raise ValueError("cell out of range")
        out[f"{x},{y}"] = names[i]
    return floor, out


def floor_key(floor: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (floor or "none").lower()).strip("_")[:40] or "none"


def avatars(persons: list, room_sources: dict[str, list[str]], states: dict[str, dict], areas: set[str], now: datetime, steady: timedelta = timedelta(minutes=2)) -> list[dict]:  # noqa: ANN001
    """Where to show a person: in a room only when the room source is clear and steady, else "in the house"."""
    out = []
    for p in persons:
        place, area = None, None
        for eid in room_sources.get(p.id, []):
            st = states.get(eid) or {}
            val = st.get("state")
            try:
                since = datetime.fromisoformat(str(st.get("last_changed")).replace("Z", "+00:00"))
            except ValueError:
                since = now
            if val in areas and now - since >= steady:
                place, area = "room", val
                break
        if place is None and any(((states.get(e) or {}).get("state") or "").lower() in ("home", "on") for e in p.sources):
            place = "house"
        if place:
            out.append({"id": p.id, "name": p.name, "place": place, "area": area})
    return out


# --- incidents -------------------------------------------------------------------------------
def incidents(deviations: list[dict], events: list[dict], meta: dict[str, dict], sides: dict[str, dict], now: datetime, days: int = 14) -> list[dict]:
    """Group deviations within ``GROUP`` into incidents with chain stages and a score (0–100)."""
    since = now - timedelta(days=days)
    devs = sorted((d for d in deviations if _ts(d) and _ts(d) >= since), key=_ts)
    groups: list[list[dict]] = []
    for d in devs:
        if groups and _ts(d) - _ts(groups[-1][-1]) <= GROUP:
            groups[-1].append(d)
        else:
            groups.append([d])
    ev = [(datetime.fromisoformat(e["ts"]), e) for e in events]
    out = []
    for g in groups:
        t0 = _ts(g[0])
        score = 0
        for d in g:
            score += KIND_SCORE.get(d["kind"], 10)
            score += int(5 * float((d.get("facts") or {}).get("bits") or 0))
        if t0.astimezone().hour < 6:
            score += 10
        door = next(((d.get("facts") or {}).get("door") for d in g if (d.get("facts") or {}).get("door")), None)
        stages = _stages(t0, door, ev, meta, sides, g)
        out.append({
            "id": g[0]["id"],
            "ts": t0.isoformat(),
            "kinds": sorted({d["kind"] for d in g}),
            "score": min(100, score),
            "status": "open" if any(d.get("status") == "open" for d in g) else "explained",
            "label": next((d.get("label") for d in g if d.get("label")), None),
            "question": next((d.get("question") for d in g if d.get("question")), None),
            "stages": stages,
            "items": g,
        })  # fmt: skip
    out.sort(key=lambda x: x["ts"], reverse=True)
    return out


def _ts(d: dict) -> datetime | None:
    try:
        return datetime.fromisoformat((d.get("facts") or {}).get("ts") or d["ts"])
    except (KeyError, TypeError, ValueError):
        return None


def _stages(t0: datetime, door: str | None, ev: list, meta: dict, sides: dict, group: list[dict]) -> list[dict]:
    def cat(eid: str) -> str:
        return (meta.get(eid) or {}).get("category") or ""

    def side(eid: str) -> str | None:
        return (sides.get(eid) or {}).get("side")

    near = [(t, e) for t, e in ev if t0 - timedelta(minutes=3) <= t <= t0 + timedelta(minutes=3)]
    approach = next(((t, e) for t, e in near if t <= t0 and e.get("kind") == "on" and cat(e["entity_id"]) == "motion" and side(e["entity_id"]) == "outside"), None)
    access = next(((t, e) for t, e in near if (door and e["entity_id"] == door and e.get("kind") == "on") or e.get("kind") == "access"), None)
    inside = next(((t, e) for t, e in near if t >= t0 and e.get("kind") == "on" and cat(e["entity_id"]) == "motion" and side(e["entity_id"]) != "outside"), None)
    if inside is None:
        sensor = next(((d.get("facts") or {}).get("sensor") for d in group if (d.get("facts") or {}).get("sensor")), None)
        if sensor:
            inside = (t0, {"entity_id": sensor})
    who = next((e for t, e in near if e.get("kind") in ("access", "person") and e.get("state") not in ("denied", "unknown", "ignore")), None)
    explained = any(d.get("status") == "explained" for d in group)

    def st(stage: str, hit, ok: bool | None = None) -> dict:  # noqa: ANN001
        return {"stage": stage, "entity": hit[1]["entity_id"] if hit else None, "ts": hit[0].isoformat() if hit else None, "ok": bool(hit) if ok is None else ok}

    return [
        st(APPROACH, approach),
        st(ACCESS, access or ((t0, {"entity_id": door}) if door else None)),
        st(INSIDE, inside),
        {"stage": IDENTITY, "entity": who["entity_id"] if who else None, "ts": None, "ok": bool(who) or explained, "who": (who or {}).get("state")},
    ]


# --- pattern entities ------------------------------------------------------------------------
def validate_pattern_entity(body: object, known_ids: set[str], taken: dict[str, str]) -> tuple[str, bool, str | None]:
    """{"id": pattern id, "on": bool, "slug": optional} – slug unique, [a-z0-9_]."""
    if not isinstance(body, dict) or not isinstance(body.get("id"), str) or body["id"] not in known_ids:
        raise ValueError("unknown pattern")
    on = body.get("on")
    if not isinstance(on, bool):
        raise ValueError("on must be true or false")
    slug = body.get("slug")
    if slug is not None and (not isinstance(slug, str) or not SLUG_RE.match(slug)):
        raise ValueError("slug: a–z, 0–9 and _ (max 40)")
    if slug and taken.get(slug) not in (None, body["id"]):
        raise ValueError("slug already used")
    if on and body["id"] not in taken.values() and len(taken) >= MAX_PATTERN_ENTITIES:
        raise ValueError(f"at most {MAX_PATTERN_ENTITIES} pattern entities")
    return body["id"], on, slug


def default_slug(item: dict) -> str:
    base = {"routine": "routine", "block": "block", "person": "person"}.get(item.get("type", ""), "pattern")
    txt = item.get("title") or item.get("goal") or item.get("id", "")
    s = re.sub(r"[^a-z0-9]+", "_", txt.lower()).strip("_")[:28]
    return f"{base}_{s}"[:40].strip("_") or f"{base}_{item.get('id', 'x')}"
