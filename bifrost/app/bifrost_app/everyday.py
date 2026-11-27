"""Everyday life (0.14) – patterns beyond arriving, leaving and sleeping, on three time scales.

All patterns are made of facts (state changes Bifrost recorded), never of opinions. Found on the last 28 days:

* **sequence** (minutes): chains that happen again and again in the same order inside an *episode* (activity
  without a gap of 10 minutes) – ≥ 3 devices in ≥ 2 rooms or ≥ 4 steps, seen on ≥ 5 days. Only *closed* chains are
  kept (a part is dropped when the longer chain explains it). Steps that always follow another within 3 s
  (motion → automatic light) are merged into the first.
* **phase** (hours): a room that is active in a block of ≥ 2 hours on most weekdays or weekend days.
* **weekly**: such a block on one weekday only (cleaner on Tuesday, washing on Saturday).
* **coupling**: B regularly follows A by 5–240 minutes (dishwasher after cooking).
* **machine**: switches on to the minute on most days – a timer, never a person.
* **break** (live): a phase that should have happened today but did not, or a device on far longer than usual.

The UI builds the names from the facts (time, rooms, devices), so they are language independent; the owner can
rename or hide each pattern. Nothing here changes a decision.
"""

from __future__ import annotations

import bisect
import hashlib
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta

GAP = timedelta(minutes=10)
MIN_DAYS = 5
MAX_STEPS = 12
STEP_KINDS = ("on", "access", "home", "away", "event", "block")
FOLLOW_S = 3
TOP = 20
DAYS = 28


def _t(v) -> datetime:  # noqa: ANN001
    """Local time (the container runs in the house's time zone, like the rest of Bifrost)."""
    return (v if isinstance(v, datetime) else datetime.fromisoformat(str(v))).astimezone()


def _id(*parts: object) -> str:
    return "ed_" + hashlib.sha1("|".join(map(str, parts)).encode(), usedforsecurity=False).hexdigest()[:10]


def _minute(t: datetime) -> int:
    return t.hour * 60 + t.minute


def _iqr(vals: list[float]) -> float:
    if len(vals) < 4:
        return (max(vals) - min(vals)) if vals else 0.0
    q = statistics.quantiles(vals, n=4)
    return q[2] - q[0]


def _token(e: dict) -> str:
    k = e.get("kind")
    return f"{e['entity_id']}:{k}" if k in ("home", "away", "access", "block") else e["entity_id"]


def followers(events: list[dict]) -> set[str]:
    """Steps that (almost) always come within 3 s after one other step – merged into it."""
    pair: Counter = Counter()
    count: Counter = Counter()
    prev = None
    for e in events:
        tok, t = _token(e), _t(e["ts"])
        count[tok] += 1
        if prev and prev[0] != tok and (t - prev[1]).total_seconds() <= FOLLOW_S:
            pair[(prev[0], tok)] += 1
        prev = (tok, t)
    return {b for (a, b), n in pair.items() if n >= 5 and n / max(1, count[b]) >= 0.9}


def episodes(events: list[dict], drop: set[str]) -> list[dict]:
    """[{"day", "start", "steps": [token…]}] – distinct steps in order of first occurrence."""
    out, cur, last = [], None, None
    for e in events:
        t = _t(e["ts"])
        tok = _token(e)
        if tok in drop:
            last = t
            continue
        if cur is None or t - last > GAP:
            cur = {"day": t.date().isoformat(), "start": t, "steps": []}
            out.append(cur)
        if tok not in cur["steps"] and len(cur["steps"]) < MAX_STEPS:
            cur["steps"].append(tok)
        last = t
    return [ep for ep in out if len(ep["steps"]) >= 3]


def sequences(eps: list[dict], area_of: dict[str, str | None]) -> list[dict]:
    seen: dict[tuple, dict] = {}
    for ep in eps:
        st = ep["steps"]
        for n in range(3, min(6, len(st)) + 1):
            for i in range(len(st) - n + 1):
                g = tuple(st[i : i + n])
                r = seen.setdefault(g, {"days": set(), "starts": [], "weekdays": Counter()})
                if ep["day"] not in r["days"]:
                    r["days"].add(ep["day"])
                    r["starts"].append(_minute(ep["start"]))
                    r["weekdays"][ep["start"].weekday()] += 1
    cand = {}
    for g, r in seen.items():
        days = len(r["days"])
        ents = {s.split(":")[0] for s in g}
        rooms = {area_of.get(x) for x in ents if area_of.get(x)}
        if days < MIN_DAYS or not ((len(ents) >= 3 and len(rooms) >= 2) or len(g) >= 4):
            continue
        cand[g] = r
    closed = {}
    for g, r in cand.items():
        n = len(r["days"])
        if any(len(h) > len(g) and any(h[i : i + len(g)] == g for i in range(len(h) - len(g) + 1)) and len(hr["days"]) >= 0.8 * n for h, hr in cand.items()):
            continue
        closed[g] = r
    out = []
    for g, r in closed.items():
        starts = r["starts"]
        med, spread = statistics.median(starts), _iqr(starts)
        regular = max(0.2, 1 - spread / 240)
        out.append({
            "id": _id("seq", *g), "kind": "sequence", "steps": list(g), "rooms": sorted({area_of.get(s.split(":")[0]) or "" for s in g} - {""}),
            "days": len(r["days"]), "at": int(med), "spread": int(spread), "weekdays": sorted(r["weekdays"]),
            "score": round(len(r["days"]) * regular * (1 + 0.15 * len(g)), 1),
        })  # fmt: skip
    return out


def _hours(events: list[dict], area_of: dict[str, str | None]) -> dict[str, dict[str, set[int]]]:
    """area → day → hours with ≥ 2 person-made events."""
    cnt: dict = defaultdict(lambda: defaultdict(Counter))
    for e in events:
        if e.get("kind") not in ("on", "access", "event"):
            continue
        a = area_of.get(e["entity_id"])
        if not a:
            continue
        t = _t(e["ts"])
        cnt[a][t.date().isoformat()][t.hour] += 1
    return {a: {d: {h for h, n in hs.items() if n >= 2} for d, hs in days.items()} for a, days in cnt.items()}


GROUPS = {"weekdays": (0, 1, 2, 3, 4), "weekend": (5, 6)}


def phases(events: list[dict], area_of: dict[str, str | None], first_day: datetime, last_day: datetime) -> list[dict]:
    hours = _hours(events, area_of)
    all_days = []
    d = first_day.date()
    while d <= last_day.date():
        all_days.append(d)
        d += timedelta(days=1)
    out = []
    for area, by_day in hours.items():
        for gname, wds in list(GROUPS.items()) + [(str(i), (i,)) for i in range(7)]:
            days = [x for x in all_days if x.weekday() in wds]
            if len(days) < (3 if len(wds) == 1 else 5):
                continue
            ratio = [sum(1 for x in days if h in by_day.get(x.isoformat(), set())) / len(days) for h in range(24)]
            blocks, start = [], None
            for h in range(25):
                on = h < 24 and ratio[h] >= 0.6
                if on and start is None:
                    start = h
                if not on and start is not None:
                    if h - start >= 2:
                        blocks.append((start, h))
                    start = None
            for b0, b1 in blocks:
                strength = statistics.fmean(ratio[b0:b1])
                rest = [ratio[h] for h in range(24) if not b0 <= h < b1]
                if b1 - b0 > 16 or not rest or strength - statistics.fmean(rest) < 0.3:
                    continue  # always busy is not a phase
                if len(wds) == 1:
                    others = [x for x in all_days if x.weekday() != wds[0]]
                    other = statistics.fmean(sum(1 for x in others if h in by_day.get(x.isoformat(), set())) / max(1, len(others)) for h in range(b0, b1))
                    if other >= 0.3:
                        continue  # not special for this weekday
                    kind = "weekly"
                else:
                    kind = "phase"
                out.append({"id": _id(kind, area, gname, b0, b1), "kind": kind, "area": area, "group": gname, "from": b0, "to": b1, "days": len(days),
                            "strength": round(strength, 2), "score": round(strength * (b1 - b0) * (2 if kind == "weekly" else 1) * 3, 1)})  # fmt: skip
    # a weekday phase that only repeats a weekday/weekend phase of the same room adds nothing
    keep = []
    for p in out:
        if p["group"] in ("0", "1", "2", "3", "4") and any(q["area"] == p["area"] and q["group"] == "weekdays" and q["from"] <= p["from"] and q["to"] >= p["to"] for q in out):
            continue
        keep.append(p)
    return keep


def _first_on(events: list[dict]) -> dict[str, dict[str, datetime]]:
    out: dict = defaultdict(dict)
    for e in events:
        if e.get("kind") not in ("on", "auto", "event"):
            continue
        t = _t(e["ts"])
        out[e["entity_id"]].setdefault(t.date().isoformat(), t)
    return out


def machines(events: list[dict]) -> list[dict]:
    """Switches on to the minute on most days (or only ever by automations)."""
    out = []
    auto = Counter(e["entity_id"] for e in events if e.get("kind") == "auto")
    on = Counter(e["entity_id"] for e in events if e.get("kind") == "on")
    cats = {e["entity_id"]: e.get("category") for e in events}
    for eid, days in _first_on(events).items():
        if len(days) < MIN_DAYS or (cats.get(eid) in ("motion", "openings", "access", "devices") and not auto[eid]):  # people, not timers
            continue
        mins = [_minute(t) for t in days.values()]
        spread = _iqr(mins)
        if spread <= 3 or (auto[eid] >= 5 and auto[eid] >= 4 * on[eid]):
            out.append({"id": _id("machine", eid), "kind": "machine", "entity_id": eid, "at": int(statistics.median(mins)), "spread": int(spread), "days": len(days), "score": round(len(days) / 2, 1)})
    return out


def _times(events: list[dict]) -> dict[str, dict[str, list[datetime]]]:
    out: dict = defaultdict(lambda: defaultdict(list))
    for e in events:
        if e.get("kind") in ("on", "auto", "event"):
            t = _t(e["ts"])
            out[e["entity_id"]][t.date().isoformat()].append(t)
    return out


def couplings(events: list[dict], exclude: set[str]) -> list[dict]:
    """B regularly follows the last A before it by 5–240 minutes (on most days B happens)."""
    # only things that happen a few times a day: for something that fires all the time, "the last one before B"
    # is always a few minutes earlier – that would be chance, not a coupling
    times = {e: d for e, d in _times(events).items() if len(d) >= MIN_DAYS and e not in exclude and sum(map(len, d.values())) / len(d) <= 4}
    top = sorted(times, key=lambda e: -len(times[e]))[:40]
    out = []
    for b in top:
        for a in top:
            if a == b:
                continue
            delays = []
            for day, bts in times[b].items():
                ats = times[a].get(day, [])
                for bt in bts:
                    k = bisect.bisect_right(ats, bt - timedelta(minutes=5))  # events are sorted: last A at least 5 min before
                    if k and (bt - ats[k - 1]).total_seconds() <= 240 * 60:
                        delays.append((bt - ats[k - 1]).total_seconds() / 60)
                        break
            if len(delays) < MIN_DAYS or len(delays) < 0.7 * len(times[b]) or _iqr(delays) > 20 or statistics.median(delays) < 10:
                continue
            out.append({"id": _id("coupling", a, b), "kind": "coupling", "a": a, "b": b, "delay": int(statistics.median(delays)), "days": len(delays), "score": round(len(delays) * 0.8, 1)})
    # keep the closest cause per effect
    best: dict[str, dict] = {}
    for c in out:
        if c["b"] not in best or c["delay"] < best[c["b"]]["delay"]:
            best[c["b"]] = c
    return list(best.values())


def durations(events: list[dict]) -> dict[str, float]:
    """p90 of how long manual/media devices stay on – for "on far longer than usual"."""
    starts: dict[str, datetime] = {}
    lens: dict[str, list[float]] = defaultdict(list)
    for e in events:
        if e.get("category") not in ("manual", "media", "openings"):
            continue
        t = _t(e["ts"])
        if e.get("kind") == "on":
            starts[e["entity_id"]] = t
        elif e.get("kind") == "off" and e["entity_id"] in starts:
            lens[e["entity_id"]].append((t - starts.pop(e["entity_id"])).total_seconds() / 60)
    return {k: round(statistics.quantiles(v, n=10)[-1], 1) for k, v in lens.items() if len(v) >= 5}


def mine(events: list[dict], area_of: dict[str, str | None], now: datetime) -> dict:
    """Everything above from the events of the last 28 days (any order)."""
    ev = sorted((e for e in events if e.get("entity_id")), key=lambda e: e["ts"])
    if not ev:
        return {"updated": now.isoformat(), "patterns": [], "durations": {}, "days": 0}
    first, last = _t(ev[0]["ts"]), _t(ev[-1]["ts"])
    steps = [e for e in ev if e.get("kind") in STEP_KINDS]
    drop = followers(steps)
    seqs = sequences(episodes(steps, drop), area_of)
    mach = machines(ev)
    pats = seqs + phases(ev, area_of, first, last) + mach + couplings(ev, {m["entity_id"] for m in mach})
    by_kind: dict[str, list] = defaultdict(list)
    for p in pats:
        by_kind[p["kind"]].append(p)
    out = []
    for lst in by_kind.values():
        out += sorted(lst, key=lambda p: -p["score"])[:TOP]
    return {"updated": now.isoformat(), "patterns": out, "durations": durations(ev), "days": (last - first).days + 1}


def breaks(model: dict, today_events: list[dict], states: dict[str, dict], area_of: dict[str, str | None], now: datetime) -> list[dict]:
    """Live: a phase that did not happen today, or a device on far longer than usual."""
    out = []
    now = now.astimezone()
    hours_today: dict = defaultdict(set)
    for e in today_events:
        a = area_of.get(e["entity_id"])
        if a:
            hours_today[a].add(_t(e["ts"]).hour)
    wd = now.weekday()
    for p in model.get("patterns", []):
        if p["kind"] not in ("phase", "weekly") or p.get("strength", 0) < 0.8:
            continue
        wds = GROUPS.get(p["group"]) or (int(p["group"]),)
        if wd not in wds or now.hour < p["to"] + 1:
            continue
        if not any(h in hours_today.get(p["area"], set()) for h in range(p["from"], p["to"])):
            out.append({"id": p["id"] + "_b", "kind": "missing", "pattern": p["id"], "area": p["area"], "from": p["from"], "to": p["to"]})
    for eid, p90 in (model.get("durations") or {}).items():
        st = states.get(eid) or {}
        if str(st.get("state")) not in ("on", "open", "playing"):
            continue
        try:
            since = _t(str(st.get("last_changed")).replace("Z", "+00:00"))
        except ValueError:
            continue
        mins = (now - since).total_seconds() / 60
        if mins > max(30, 3 * p90):
            out.append({"id": _id("long", eid), "kind": "long_on", "entity_id": eid, "minutes": int(mins), "usual": p90})
    return out
