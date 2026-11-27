"""Baselines and paths (0.9) – two of the detectors of the control room.

* **Baseline** (like behaviour baselines in security monitoring): for every signal and every hour of the
  week Bifrost counts in how many weeks it fired. A firing at an hour where it (almost) never fires is
  *rare*; its surprise is measured in bits (−log2 p). Rare moments become the deviation kind "rare".
* **Path matrix**: indoor motion in area A followed within a minute by motion in area B is a walk A → B.
  The matrix of walks (count and typical seconds) shows how people move – a grid instead of a drawn graph,
  so nothing crosses and it fits a phone. A first indoor motion while the house was empty without any door
  is a *contradiction* (a fixed rule, see brain).

Pure functions, only counters are stored – no raw events.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import datetime, timedelta

SLOTS = 7 * 24
ACTIVITY = ("motion", "openings", "manual", "media", "access")
RARE_BITS = 3.3  # p < 0.1 – and never seen at this hour or the hours next to it
MIN_WEEKS = 3
MIN_TOTAL = 20
WALK = 60  # seconds


def slot(t: datetime) -> int:
    lt = t.astimezone()
    return lt.weekday() * 24 + lt.hour


def _t(v) -> datetime:  # noqa: ANN001
    return v if isinstance(v, datetime) else datetime.fromisoformat(str(v))


def learn(events: list[dict], meta: dict[str, dict]) -> dict:
    """Per signal and hour of week: in how many distinct weeks did it fire."""
    weeks: dict[str, dict[int, set]] = defaultdict(lambda: defaultdict(set))
    total: dict[str, int] = defaultdict(int)
    first = last = None
    for e in events:
        if e.get("kind") not in ("on", "access"):
            continue
        cat = (meta.get(e["entity_id"]) or {}).get("category") or ("access" if e.get("kind") == "access" else "")
        if cat not in ACTIVITY:
            continue
        t = _t(e["ts"])
        first = t if first is None or t < first else first
        last = t if last is None or t > last else last
        iso = t.astimezone().isocalendar()
        weeks[e["entity_id"]][slot(t)].add((iso[0], iso[1]))
        total[e["entity_id"]] += 1
    n_weeks = max(1, round(((last - first).total_seconds() / 604800) if first and last else 0) + 1)
    return {
        "weeks": n_weeks,
        "signals": {eid: {"total": total[eid], "slots": {str(k): len(v) for k, v in sl.items()}} for eid, sl in weeks.items()},
    }


def rarity(model: dict, entity_id: str, t: datetime) -> float | None:
    """Surprise in bits of this signal firing at this hour of the week, or None if not enough history."""
    sig = (model.get("signals") or {}).get(entity_id)
    n = int(model.get("weeks") or 0)
    if not sig or n < MIN_WEEKS or sig.get("total", 0) < MIN_TOTAL:
        return None
    k = int((sig.get("slots") or {}).get(str(slot(t)), 0))
    p = (k + 0.5) / (n + 1)
    return round(-math.log2(min(1.0, p)), 2)


def is_rare(model: dict, entity_id: str, t: datetime) -> float | None:
    """Bits of surprise if this firing is rare: never at this hour of the week nor the hours next to it."""
    bits = rarity(model, entity_id, t)
    if bits is None or bits < RARE_BITS:
        return None
    slots = model["signals"][entity_id].get("slots") or {}
    sl = slot(t)
    if any(int(slots.get(str((sl + d) % SLOTS), 0)) for d in (-1, 1)):
        return None
    return bits


def heat(model: dict, entity_id: str) -> list[float]:
    """168 values 0…1: share of weeks the signal fired in each hour of the week (Mon 0:00 first)."""
    sig = (model.get("signals") or {}).get(entity_id) or {}
    n = max(1, int(model.get("weeks") or 1))
    return [round(min(1.0, int((sig.get("slots") or {}).get(str(i), 0)) / n), 2) for i in range(SLOTS)]


def paths(events: list[dict], meta: dict[str, dict], sides: dict[str, dict] | None = None) -> dict:
    """Walks between areas: consecutive indoor motions in different areas within ``WALK`` seconds."""
    sides = sides or {}
    mon = sorted(
        ((_t(e["ts"]), (meta.get(e["entity_id"]) or {}).get("area")) for e in events
         if e.get("kind") == "on" and (meta.get(e["entity_id"]) or {}).get("category") == "motion"
         and (sides.get(e["entity_id"]) or {}).get("side") != "outside" and (meta.get(e["entity_id"]) or {}).get("area")),
        key=lambda x: x[0],
    )  # fmt: skip
    walks: dict[tuple[str, str], list[float]] = defaultdict(list)
    for (t1, a1), (t2, a2) in zip(mon, mon[1:], strict=False):
        dt = (t2 - t1).total_seconds()
        if a1 != a2 and 0 < dt <= WALK:
            walks[(a1, a2)].append(dt)
    areas = sorted({a for k in walks for a in k})
    cells = [[{"n": len(walks.get((a, b), [])), "s": round(statistics.median(walks[(a, b)])) if walks.get((a, b)) else None} for b in areas] for a in areas]
    return {"areas": areas, "cells": cells}


def motion_without_entry(edge_ts: datetime, last_door: datetime | None, hold: timedelta = timedelta(minutes=3)) -> bool:
    """Indoor motion while the house is empty with no door shortly before – the fixed contradiction rule."""
    return last_door is None or edge_ts - last_door > hold
