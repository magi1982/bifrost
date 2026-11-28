"""Hindsight labels (0.8) – the truth Bifrost learns from, never its own live decision.

Looking back, many moments are certain even though they were not certain while they happened:

* **certainly home** – somebody was active inside (motion that is not isolated, a light switched by
  hand, media, an unlock, a "someone home" mode); and a long quiet stretch after which activity resumes
  inside without anybody coming in – somebody stayed inside (reading, sleeping, a child without a phone),
  even if others left at its start.
* **certainly empty** – a quiet stretch that starts with a confirmed exit (an outside sensor right after
  the door, or every tracked phone leaving) and ends with an entry (outside → door, an unlock, a phone
  coming home). An alarm panel "armed away" and the owner's "That's wrong" are certain as well.
* everything else is **unclear** and is not used for learning.

Isolated single motions inside an empty stretch (no other sensor, no door nearby) do not break it –
they are reported as disturbance candidates (animals, a robot, a draft).

The module is pure: events in, labelled segments out. Nothing here reads the live decision.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from datetime import datetime, timedelta

HOME, EMPTY, UNCLEAR = "home", "empty", "unclear"
STRONG, MEDIUM = "strong", "medium"
GAP = timedelta(minutes=20)  # quiet longer than this is a stretch worth labelling
ISOLATED_OTHER = timedelta(seconds=60)
ISOLATED_DOOR = timedelta(minutes=2)
EXIT_BEFORE, EXIT_AFTER = timedelta(minutes=5), timedelta(minutes=15)
ENTRY_BEFORE, ENTRY_AFTER = timedelta(minutes=10), timedelta(minutes=2)
PHONE_LEAVE = timedelta(minutes=20)
CONFIRM = timedelta(seconds=90)  # outside sensor after/before a door
ACTIVITY_CATS = ("manual", "media")
MIN_WRONG = timedelta(minutes=5)
SUSTAINED = timedelta(minutes=30)
MAX_WEAK = 2  # isolated motions an empty stretch may contain (animals, robots) before it is not called empty
DENIED = ("denied", "ignore")


def _t(v) -> datetime:  # noqa: ANN001
    return v if isinstance(v, datetime) else datetime.fromisoformat(str(v))


def _in(times: list[datetime], a: datetime, b: datetime) -> bool:
    i = bisect_left(times, a)
    return i < len(times) and times[i] <= b


def label(  # noqa: C901
    events: list[dict],
    meta: dict[str, dict],
    sides: dict[str, dict] | None = None,
    exceptions: set[str] | None = None,
    owner_labels: list[dict] | None = None,
) -> dict:
    """Label the history. events: store rows (ts, entity_id, kind, state); meta: entity → {category, ...}."""
    sides = sides or {}
    exceptions = exceptions or set()
    ev = sorted(({**e, "_t": _t(e["ts"])} for e in events), key=lambda e: e["_t"])
    if not ev:
        return {"segments": [], "disturbances": [], "departures": [], "arrivals": [], "stats": {"home_h": 0, "empty_h": 0, "unclear_h": 0}}

    def cat(eid: str) -> str:
        return (meta.get(eid) or {}).get("category") or ""

    def is_outside(eid: str) -> bool:
        return (sides.get(eid) or {}).get("side") == "outside"

    doors = [e["_t"] for e in ev if e.get("kind") == "on" and cat(e["entity_id"]) == "openings"]
    door_ev = [e for e in ev if e.get("kind") == "on" and cat(e["entity_id"]) == "openings"]
    outside = [e["_t"] for e in ev if e.get("kind") == "on" and cat(e["entity_id"]) == "motion" and is_outside(e["entity_id"])]

    # --- activity points inside: strong and weak (isolated motion)
    points: list[tuple[datetime, str, bool]] = []  # (time, entity, strong)
    motion = [e for e in ev if e.get("kind") == "on" and cat(e["entity_id"]) == "motion" and not is_outside(e["entity_id"]) and e["entity_id"] not in exceptions]
    motion_t = [e["_t"] for e in motion]
    for e in motion:
        t = e["_t"]
        lo, hi = bisect_left(motion_t, t - ISOLATED_OTHER), bisect_right(motion_t, t + ISOLATED_OTHER)
        other = any(motion[i]["entity_id"] != e["entity_id"] for i in range(lo, hi))
        near_door = _in(doors, t - ISOLATED_DOOR, t + ISOLATED_DOOR)
        # motion again within half an hour is somebody there, not a passing animal (safety first:
        # real disturbances are confirmed by the owner once and then left out completely)
        lo2, hi2 = bisect_left(motion_t, t - SUSTAINED), bisect_right(motion_t, t + SUSTAINED)
        sustained = hi2 - lo2 > 1
        points.append((t, e["entity_id"], other or near_door or sustained))
    for e in ev:
        c, k = cat(e["entity_id"]), e.get("kind")
        if (c in ACTIVITY_CATS and k == "on") or (c == "mode_home" and k == "on") or (k == "access" and e.get("state") not in DENIED):
            points.append((e["_t"], e["entity_id"], True))
    points.sort()
    strong = [p for p in points if p[2]]
    weak = [p for p in points if not p[2]]

    # --- identities
    phone_home = [e["_t"] for e in ev if e.get("kind") == "home"]
    phone_away = [e for e in ev if e.get("kind") == "away"]
    access = [e["_t"] for e in ev if e.get("kind") == "access" and e.get("state") not in DENIED]
    blocks_exit = [e["_t"] for e in ev if e.get("kind") == "block" and str(e.get("state", "")).startswith("exit:")]
    blocks_entry = [e["_t"] for e in ev if e.get("kind") == "block" and str(e.get("state", "")).startswith("entry:")]
    trackers = sorted({e["entity_id"] for e in ev if e.get("kind") in ("home", "away")})

    by_tracker: dict[str, tuple[list[datetime], list[str]]] = {}
    for e in ev:
        if e.get("kind") in ("home", "away"):
            ts_, ks = by_tracker.setdefault(e["entity_id"], ([], []))
            ts_.append(e["_t"])
            ks.append(e["kind"])

    def tracker_state_before(eid: str, t: datetime) -> str | None:
        ts_, ks = by_tracker.get(eid, ([], []))
        i = bisect_left(ts_, t)
        return ks[i - 1] if i else None

    def confirmed_exit(a: datetime) -> bool:
        if _in(blocks_exit, a - EXIT_BEFORE, a + EXIT_AFTER):
            return True
        for d in door_ev:
            if a - EXIT_BEFORE <= d["_t"] <= a + EXIT_AFTER and _in(outside, d["_t"], d["_t"] + CONFIRM):
                return True
        return False

    def phones_left(a: datetime) -> bool:
        if not trackers:
            return False
        left = {e["entity_id"] for e in phone_away if a - PHONE_LEAVE / 2 <= e["_t"] <= a + PHONE_LEAVE}
        home_before = [x for x in trackers if tracker_state_before(x, a - PHONE_LEAVE / 2) != "away"]
        return bool(left) and all(x in left for x in home_before)

    def entry_door_near(b: datetime) -> bool:
        """A door near the end of a quiet stretch that is not a confirmed exit – somebody may have come in."""
        return any(b - ENTRY_BEFORE <= d["_t"] <= b + ENTRY_AFTER and not _in(outside, d["_t"], d["_t"] + CONFIRM) for d in door_ev)

    def entry(b: datetime) -> bool:
        if _in(blocks_entry, b - ENTRY_BEFORE, b + ENTRY_AFTER) or _in(access, b - ENTRY_BEFORE, b + ENTRY_AFTER):
            return True
        if _in(phone_home, b - ENTRY_BEFORE - timedelta(minutes=5), b + ENTRY_AFTER):
            return True
        for d in door_ev:
            if b - ENTRY_BEFORE <= d["_t"] <= b + ENTRY_AFTER and _in(outside, d["_t"] - CONFIRM - CONFIRM, d["_t"]):
                return True
        return False

    segments: list[dict] = []
    disturbances: list[dict] = []
    departures: list[datetime] = []
    arrivals: list[datetime] = []
    if strong:
        burst_start = strong[0][0]
        prev = strong[0][0]
        for t, _eid, _s in strong[1:]:
            if t - prev > GAP:
                segments.append({"start": burst_start, "end": prev, "label": HOME, "strength": STRONG, "why": "activity"})
                ex, pl, en = confirmed_exit(prev), phones_left(prev), entry(t)
                inside = [w for w in weak if prev < w[0] < t]
                if (ex or pl) and en and len(inside) > MAX_WEAK:
                    # repeated "isolated" motion is somebody alone in a room, not an animal – never call it empty
                    segments.append({"start": prev, "end": t, "label": UNCLEAR, "strength": None, "why": "motion_inside"})
                elif (ex or pl) and en:
                    segments.append({"start": prev, "end": t, "label": EMPTY, "strength": STRONG if ex else MEDIUM, "why": "exit_then_entry" if ex else "phones_then_entry"})
                    departures.append(prev)
                    arrivals.append(t)
                    disturbances += [{"entity_id": w[1], "ts": w[0].isoformat()} for w in inside]
                elif not en and not entry_door_near(t):
                    # activity resumed inside and nobody came in: somebody was inside the whole time
                    segments.append({"start": prev, "end": t, "label": HOME, "strength": MEDIUM, "why": "stayed_inside"})
                else:
                    segments.append({"start": prev, "end": t, "label": UNCLEAR, "strength": None, "why": "open_end"})
                burst_start = t
            prev = t
        segments.append({"start": burst_start, "end": prev, "label": HOME, "strength": STRONG, "why": "activity"})

    # alarm panel armed away: certain
    for i, e in enumerate(ev):
        if str(e["entity_id"]).startswith("alarm_control_panel.") and e.get("state") == "armed_away":
            end = next((x["_t"] for x in ev[i + 1 :] if x["entity_id"] == e["entity_id"]), None)
            if end:
                segments = _override(segments, e["_t"], end, EMPTY, STRONG, "alarm_armed_away")
    # the owner said what was true
    for lab in owner_labels or []:
        if lab.get("person"):
            continue
        try:
            t = _t(lab["ts"])
        except (KeyError, ValueError):
            continue
        actual = EMPTY if lab.get("actual") == "away" else HOME
        seg = next((s for s in segments if s["start"] <= t <= s["end"] and s["why"] != "activity"), None)
        if seg:
            seg.update(label=actual, strength=STRONG if lab.get("_w", 1.0) >= 0.5 else MEDIUM, why="owner")

    stats = {k + "_h": round(sum((s["end"] - s["start"]).total_seconds() for s in segments if s["label"] == v) / 3600, 1) for k, v in (("home", HOME), ("empty", EMPTY), ("unclear", UNCLEAR))}
    return {"segments": segments, "disturbances": disturbances, "departures": departures, "arrivals": arrivals, "stats": stats}


def _override(segments: list[dict], a: datetime, b: datetime, lab: str, strength: str, why: str) -> list[dict]:
    out = []
    for s in segments:
        if s["end"] <= a or s["start"] >= b or s["why"] == "activity":
            out.append(s)
            continue
        out.append({**s, "label": lab, "strength": strength, "why": why})
    return out


def to_decisions(result: dict) -> list[dict]:
    """Segments as a decision-like timeline (home / away / unknown) for learners that need one."""
    out: list[dict] = []
    segs = sorted(result["segments"], key=lambda s: s["start"])
    for i, s in enumerate(segs):
        state = {HOME: "home", EMPTY: "away"}.get(s["label"], "unknown")
        out.append({"ts": s["start"].isoformat(), "state": state})
        if i + 1 == len(segs) or segs[i + 1]["start"] > s["end"]:
            out.append({"ts": s["end"].isoformat(), "state": "unknown"})  # a gap: nothing is known
    return out


def label_at(result: dict, t: datetime) -> str | None:
    for s in result["segments"]:
        if s["start"] <= t <= s["end"]:
            return s["label"]
    return None


def wrong_empty(result: dict, decisions: list[dict], parse) -> list[dict]:  # noqa: ANN001
    """Moments Bifrost said "empty" while hindsight is sure somebody was inside – the backtest's key figure."""
    dec = sorted((parse(d["ts"]), d["state"]) for d in decisions)
    away = [(t, dec[i + 1][0] if i + 1 < len(dec) else t + timedelta(minutes=15)) for i, (t, st) in enumerate(dec) if st == "away"]
    out = []
    for s in result["segments"]:
        if s["label"] != HOME:
            continue
        for a, b in away:
            lo, hi = max(a, s["start"]), min(b, s["end"])
            if hi - lo >= MIN_WRONG:  # a few minutes of delay at an arrival are no mistake
                out.append({"from": lo.isoformat(), "to": hi.isoformat(), "why": s["why"]})
                break
    return out
