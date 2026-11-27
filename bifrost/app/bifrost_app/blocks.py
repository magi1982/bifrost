"""Blocks (0.4) – Bifrost learns how *this* house works, without knowing names or rooms.

Learned from clean edge events (see preprocess.py), no home/away outcome needed:

* **Neighbours and walking times** – motion A then motion B within seconds, again and again →
  A and B are neighbours; this builds the house map.
* **Inside / outside sensors** – a motion sensor that fires *before* doors open, or while the house
  was empty, is outside; one that fires right *after* doors open is inside.
* **Entrances and door direction** – outside → door → inside = entry; inside → door → (outside) = exit;
  inside before and after = opened from inside only (ventilation, garden, letting someone in).
* **Door profiles** – entries / exits / inside-only per door and time of day → role suggestions.
* **Known disturbances** – isolated motion without door and without neighbour while nobody is home.
* **Sensor doctor** – dead sensors, chatty sensors, trackers that are almost never home.

Everything is a suggestion with numbers; nothing here decides alone.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime, timedelta

NEIGHBOUR_WINDOW = 30  # s: B after A within this time counts as a walk A → B
MIN_NEIGHBOUR = 5
BEFORE_WINDOW = 60  # s before a door opens
AFTER_WINDOW = 45  # s after a door opens
INSIDE_QUIET = 120  # s without inside motion before an entry
EXIT_SILENCE = 600  # s without inside motion after an exit
MIN_SIDE = 5
MIN_DISTURB = 3
QUIET = 600  # s of no motion at all = the house is quiet

OUTSIDE_WORDS = ("aussen", "außen", "outside", "outdoor", "garten", "garden", "terrasse", "terrace", "sitzplatz", "einfahrt", "driveway", "vorplatz", "carport")
DOOR_CLASSES = ("door", "garage_door", "opening")
DOOR_WORDS = ("tür", "tuer", "türe", "door", "tor", "gate")
WINDOW_WORDS = ("fenster", "window")
# windows people walk through: sliding doors and floor-length windows to the garden or terrace
PASSAGE_WORDS = ("schiebe", "hebeschiebe", "hst", "bodentief", "terrass", "terrace", "garten", "garden", "sitzplatz", "balkon", "balcony", "patio", "sliding", "french")

ENTRY, EXIT, INSIDE_ONLY, UNKNOWN = "entry", "exit", "inside_only", "unknown"
BUCKETS = (("night", 0, 6), ("morning", 6, 12), ("afternoon", 12, 18), ("evening", 18, 24))


def _ts(v) -> datetime:  # noqa: ANN001
    return v if isinstance(v, datetime) else datetime.fromisoformat(str(v))


def bucket(ts: datetime) -> str:
    h = ts.astimezone().hour
    for name, a, b in BUCKETS:
        if a <= h < b:
            return name
    return "night"


def is_door(meta: dict) -> bool:
    """Doors and passable windows. The name wins over the device class: many contacts are set up as "window"."""
    dc = (meta.get("device_class") or "").lower()
    name = (meta.get("name") or "").lower() + " " + meta.get("entity_id", "").lower()
    opening = dc in DOOR_CLASSES or dc == "window" or meta.get("category") == "openings"
    if not opening:
        return False
    if any(w in name for w in DOOR_WORDS) or any(w in name for w in PASSAGE_WORDS):
        return True
    if dc == "window" or any(w in name for w in WINDOW_WORDS):
        return False
    return dc in DOOR_CLASSES


def is_motion(meta: dict) -> bool:
    return meta.get("category") == "motion" and meta.get("entity_id", "").startswith("binary_sensor.")


def outside_hint(meta: dict) -> bool:
    text = " ".join(str(meta.get(k) or "") for k in ("name", "area", "entity_id")).lower()
    return any(w in text for w in OUTSIDE_WORDS)


def _pct(vals: list[float], q: float) -> float:
    s = sorted(vals)
    return s[min(len(s) - 1, max(0, round(q * (len(s) - 1))))]


def _away_at(decisions: list[tuple[datetime, str]], ts: datetime) -> bool:
    state = None
    for t, st in decisions:
        if t > ts:
            break
        state = st
    return state == "away"


def learn(events: list[dict], meta: dict[str, dict], decisions: list[dict] | None = None) -> dict:
    """Learn the house model from edge events (oldest or newest first, any order)."""
    ev = sorted(({**e, "_t": _ts(e["ts"])} for e in events if e.get("kind") in ("on", "off", "home", "away")), key=lambda e: e["_t"])
    dec = sorted((_ts(d["ts"]), d["state"]) for d in (decisions or []))
    motions = {eid for eid, m in meta.items() if is_motion({**m, "entity_id": eid})}
    doors = {eid for eid, m in meta.items() if is_door({**m, "entity_id": eid})}
    mon = [e for e in ev if e["kind"] == "on" and e["entity_id"] in motions]
    dopen = [e for e in ev if e["kind"] == "on" and e["entity_id"] in doors]

    # --- neighbours and walking times
    walks: dict[tuple[str, str], list[float]] = defaultdict(list)
    for prev, cur in zip(mon, mon[1:], strict=False):
        dt = (cur["_t"] - prev["_t"]).total_seconds()
        if prev["entity_id"] != cur["entity_id"] and 0 < dt <= NEIGHBOUR_WINDOW:
            a, b = sorted((prev["entity_id"], cur["entity_id"]))
            walks[(a, b)].append(dt)
    neighbours = [
        {"a": a, "b": b, "count": len(v), "walk": {"min": round(_pct(v, 0.1), 1), "typical": round(statistics.median(v), 1), "max": round(_pct(v, 0.9), 1)}}
        for (a, b), v in walks.items()
        if len(v) >= MIN_NEIGHBOUR
    ]

    # --- which sensors fire before / after doors, in entry and exit situations
    # entry situation: the house was quiet before the door opened and becomes active after it
    #   → sensors right before the door are outside, sensors right after it are inside
    # exit situation: the house was active before and becomes quiet after
    #   → sensors right before the door are inside, sensors right after it are outside
    before: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    after: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    vote_in: dict[str, int] = defaultdict(int)
    vote_out: dict[str, int] = defaultdict(int)
    door_in: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    door_out: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for d in dopen:
        t = d["_t"]
        nb = [m for m in mon if -BEFORE_WINDOW <= (m["_t"] - t).total_seconds() < 0]
        na = [m for m in mon if 0 <= (m["_t"] - t).total_seconds() <= AFTER_WINDOW]
        near_b, near_a = {m["entity_id"] for m in nb}, {m["entity_id"] for m in na}
        closest_b = nb[-1]["entity_id"] if nb else None  # the sensor right next to the door
        closest_a = na[0]["entity_id"] if na else None
        for x in near_b:
            before[d["entity_id"]][x] += 1
        for x in near_a:
            after[d["entity_id"]][x] += 1
        quiet_before = not any(-QUIET <= (m["_t"] - t).total_seconds() < -BEFORE_WINDOW for m in mon)
        silent_after = not any(AFTER_WINDOW < (m["_t"] - t).total_seconds() <= QUIET for m in mon)
        if quiet_before and not silent_after:  # entry
            for x in near_b:
                vote_out[x] += 1
            for x in near_a:
                vote_in[x] += 1
            if closest_b:
                door_out[d["entity_id"]][closest_b] += 1
            if closest_a:
                door_in[d["entity_id"]][closest_a] += 1
        elif silent_after and not quiet_before:  # exit
            for x in near_b:
                vote_in[x] += 1
            for x in near_a:
                vote_out[x] += 1
            if closest_b:
                door_in[d["entity_id"]][closest_b] += 1
            if closest_a:
                door_out[d["entity_id"]][closest_a] += 1

    # --- inside / outside per motion sensor
    sides: dict[str, dict] = {}
    for s in sorted(motions):
        b = sum(before[d][s] for d in doors)
        a = sum(after[d][s] for d in doors)
        total = sum(1 for m in mon if m["entity_id"] == s)
        away = sum(1 for m in mon if m["entity_id"] == s and _away_at(dec, m["_t"]))
        away_rate = away / total if total else 0.0
        vi, vo = vote_in[s], vote_out[s]
        hint = outside_hint({**meta.get(s, {}), "entity_id": s})
        if vo >= 3 and vo >= 2 * vi:
            side, why = "outside", "fires before arrivals / after departures"
        elif vi >= 3 and vi >= 2 * vo:
            side, why = "inside", "fires after arrivals / before departures"
        elif total >= MIN_SIDE and away_rate >= 0.5:
            side, why = "outside", "fires while nobody is home"
        elif hint:
            side, why = "outside", "name/area"
        elif total >= MIN_SIDE:
            side, why = "inside", "default"
        else:
            side, why = "unknown", "not enough data"
        sides[s] = {"side": side, "why": why, "votes_inside": vi, "votes_outside": vo, "before_doors": b, "after_doors": a, "edges": total, "away_rate": round(away_rate, 2)}

    # --- entrances
    entrances = []
    for d in sorted(doors):
        ins = sorted(((n, x) for x, n in door_in[d].items() if sides.get(x, {}).get("side") == "inside"), reverse=True)
        outs = sorted(((n, x) for x, n in door_out[d].items() if sides.get(x, {}).get("side") == "outside"), reverse=True)
        n = sum(1 for e in dopen if e["entity_id"] == d)
        entrances.append(
            {
                "door": d,
                "openings": n,
                "inside": ins[0][1] if ins and ins[0][0] >= 3 else None,
                "outside": outs[0][1] if outs and outs[0][0] >= 3 else None,
            }
        )
    for en in entrances:
        en["direction"] = bool(en["inside"])  # direction needs at least an inside sensor

    model = {"neighbours": neighbours, "sides": sides, "entrances": entrances, "doors": sorted(doors), "motions": sorted(motions)}
    # --- door profiles (classify every past opening)
    profiles: dict[str, dict[str, dict[str, int]]] = {}
    for d in dopen:
        c = classify_opening(model, d["entity_id"], d["_t"], mon)
        prof = profiles.setdefault(d["entity_id"], {b[0]: {ENTRY: 0, EXIT: 0, INSIDE_ONLY: 0, UNKNOWN: 0} for b in BUCKETS})
        prof[bucket(d["_t"])][c] += 1
    model["profiles"] = profiles
    model["roles"] = {d: door_role(p) for d, p in profiles.items()}

    # --- known disturbances: isolated motion while nobody is home
    disturb: dict[str, int] = defaultdict(int)
    for m in mon:
        if not _away_at(dec, m["_t"]):
            continue
        t = m["_t"]
        near_door = any(abs((d["_t"] - t).total_seconds()) <= INSIDE_QUIET for d in dopen)
        near_other = any(o is not m and o["entity_id"] != m["entity_id"] and abs((o["_t"] - t).total_seconds()) <= 60 for o in mon)
        if not near_door and not near_other:
            disturb[m["entity_id"]] += 1
    model["disturbances"] = [{"sensor": s, "count": n} for s, n in sorted(disturb.items(), key=lambda x: -x[1]) if n >= MIN_DISTURB]
    model["map"] = house_map(model)
    return model


def classify_opening(model: dict, door: str, t: datetime, motion_on: list[dict]) -> str:
    """entry / exit / inside_only / unknown for one door opening at time t."""
    sides = model.get("sides", {})
    en = next((e for e in model.get("entrances", []) if e["door"] == door), None)
    inside_s = {s for s, v in sides.items() if v["side"] == "inside"}

    def fired(sensors: set[str], a: float, b: float) -> bool:
        return any(m["entity_id"] in sensors and a <= (m["_t"] - t).total_seconds() <= b for m in motion_on)

    in_before = fired(inside_s, -INSIDE_QUIET, -0.001)
    in_after = fired(inside_s, 0, AFTER_WINDOW)
    in_later = fired(inside_s, AFTER_WINDOW, EXIT_SILENCE)
    if not en or not en.get("inside"):
        # no sensor right at this door: only "opened from inside" can be told
        return INSIDE_ONLY if in_before and (in_after or in_later) else UNKNOWN
    if not in_before and in_after:
        return ENTRY
    if in_before and (in_after or in_later):
        return INSIDE_ONLY
    if in_before and not in_after and not in_later:
        return EXIT
    return UNKNOWN


def door_role(profile: dict[str, dict[str, int]]) -> dict:
    tot = {k: sum(b[k] for b in profile.values()) for k in (ENTRY, EXIT, INSIDE_ONLY, UNKNOWN)}
    n = sum(tot.values())
    if n < 5:
        return {"role": "unknown", "why": "not enough openings", **tot}
    if tot[ENTRY] + tot[EXIT] >= 0.3 * n:
        return {"role": "entrance", "why": f"{tot[ENTRY]} entries, {tot[EXIT]} exits", **tot}
    if tot[INSIDE_ONLY] >= 0.6 * n:
        return {"role": "inside_only", "why": f"{tot[INSIDE_ONLY]} of {n} only opened from inside", **tot}
    return {"role": "unknown", "why": "mixed use", **tot}


def house_map(model: dict) -> dict:
    """Nodes and links for the House tab (learned graph, no floor plan needed)."""
    nodes = []
    for s, v in model.get("sides", {}).items():
        nodes.append({"id": s, "type": "motion", "side": v["side"]})
    for d in model.get("doors", []):
        nodes.append({"id": d, "type": "door", "side": "between", "role": model.get("roles", {}).get(d, {}).get("role", "unknown")})
    links = [{"a": n["a"], "b": n["b"], "kind": "walk", "count": n["count"], "typical": n["walk"]["typical"]} for n in model.get("neighbours", [])]
    for en in model.get("entrances", []):
        if en.get("inside"):
            links.append({"a": en["door"], "b": en["inside"], "kind": "door_inside"})
        if en.get("outside"):
            links.append({"a": en["outside"], "b": en["door"], "kind": "door_outside"})
    return {"nodes": nodes, "links": links}


def min_people(model: dict, motion_on: list[dict], now: datetime, window: int = 120) -> int:
    """Lower bound of people inside: two inside sensors firing faster than anyone can walk between them."""
    walk = {tuple(sorted((n["a"], n["b"]))): n["walk"]["min"] for n in model.get("neighbours", [])}
    inside = {s for s, v in model.get("sides", {}).items() if v["side"] == "inside"}
    recent = [m for m in motion_on if m["entity_id"] in inside and 0 <= (now - m["_t"]).total_seconds() <= window]
    best = 1 if recent else 0
    for i, a in enumerate(recent):
        for b in recent[i + 1 :]:
            if a["entity_id"] == b["entity_id"]:
                continue
            dt = abs((a["_t"] - b["_t"]).total_seconds())
            need = walk.get(tuple(sorted((a["entity_id"], b["entity_id"]))), 8.0)  # non-neighbours: at least 8 s
            if dt + 0.5 < need * 0.6:
                best = max(best, 2)
    return best


def sensor_doctor(events: list[dict], meta: dict[str, dict], days: float, current: dict[str, str | None] | None = None) -> list[dict]:
    """Dead, chatty and almost-never-home signals."""
    current = current or {}
    if days < 3:
        return []
    ons: dict[str, int] = defaultdict(int)
    gaps: dict[str, int] = defaultdict(int)
    homes: dict[str, int] = defaultdict(int)
    for e in events:
        if e.get("kind") == "on":
            ons[e["entity_id"]] += 1
        elif e.get("kind") == "gap":
            gaps[e["entity_id"]] += 1
        elif e.get("kind") == "home":
            homes[e["entity_id"]] += 1
    out = []
    by_cat: dict[str, list[float]] = defaultdict(list)
    for eid, m in meta.items():
        if m.get("category") in ("motion", "openings"):
            by_cat[m["category"]].append(ons.get(eid, 0) / days)
    for eid, m in meta.items():
        cat = m.get("category")
        if cat in ("motion", "openings"):
            per_day = ons.get(eid, 0) / days
            med = statistics.median(by_cat[cat]) if by_cat[cat] else 0
            if ons.get(eid, 0) == 0 and any(v > 0 for v in by_cat[cat]):
                out.append({"entity_id": eid, "problem": "dead", "detail": f"no activity in {days:.0f} days"})
            elif per_day > 50 and per_day > 5 * max(med, 1):
                out.append({"entity_id": eid, "problem": "chatty", "detail": f"{per_day:.0f}× per day (typical {med:.0f})"})
        if eid.startswith("device_tracker.") and m.get("category") == "devices":
            if homes.get(eid, 0) == 0 and (current.get(eid) or "") != "home":
                out.append({"entity_id": eid, "problem": "never_home", "detail": f"not home once in {days:.0f} days"})
        if gaps.get(eid, 0) >= max(5, days):
            out.append({"entity_id": eid, "problem": "gaps", "detail": f"{gaps[eid]}× unavailable"})
    return out


def capability(model: dict, people_total: int, people_with_source: int) -> dict:
    ens = model.get("entrances", [])
    sides = model.get("sides", {})
    return {
        "doors": len(model.get("doors", [])),
        "doors_with_direction": sum(1 for e in ens if e.get("direction")),
        "inside_sensors": sum(1 for v in sides.values() if v["side"] == "inside"),
        "outside_sensors": sum(1 for v in sides.values() if v["side"] == "outside"),
        "neighbours": len(model.get("neighbours", [])),
        "people": people_total,
        "people_with_source": people_with_source,
        "missing": [
            m
            for m, cond in (
                ("door_contacts", not model.get("doors")),
                ("inside_motion_near_doors", ens and not any(e.get("inside") for e in ens)),
                ("outside_motion", not any(v["side"] == "outside" for v in sides.values())),
                ("people", people_total == 0),
                ("people_sources", people_total > people_with_source),
            )
            if cond
        ],
    }


class Detector:
    """Live: classify door openings once enough time has passed, count people, find isolated motion."""

    def __init__(self) -> None:
        self.model: dict = {}
        self.recent: list[dict] = []
        self.pending: list[dict] = []  # door openings waiting for their "after" window

    def feed(self, edge: dict) -> None:
        e = {**edge, "_t": _ts(edge["ts"])}
        if e.get("kind") != "on":
            return
        self.recent.append(e)
        if e["entity_id"] in set(self.model.get("doors", [])):
            self.pending.append(e)

    def tick(self, now: datetime) -> list[dict]:
        """Return newly classified openings: {door, ts, result}."""
        cutoff = now - timedelta(seconds=EXIT_SILENCE + INSIDE_QUIET)
        self.recent = [r for r in self.recent if r["_t"] >= cutoff]
        out, keep = [], []
        motions = set(self.model.get("motions", []))
        mon = [r for r in self.recent if r["entity_id"] in motions]
        for p in self.pending:
            age = (now - p["_t"]).total_seconds()
            if age < AFTER_WINDOW:
                keep.append(p)
                continue
            res = classify_opening(self.model, p["entity_id"], p["_t"], mon)
            if res == EXIT and age < EXIT_SILENCE:
                keep.append(p)  # an exit is only sure after the silence
                continue
            out.append({"door": p["entity_id"], "ts": p["_t"].isoformat(), "result": res})
        self.pending = keep
        return out

    def people_inside_min(self, now: datetime) -> int:
        motions = set(self.model.get("motions", []))
        return min_people(self.model, [r for r in self.recent if r["entity_id"] in motions], now)
