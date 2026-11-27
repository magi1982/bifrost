"""Calendar learning 2.0 (0.6) – every frequently used word, five effects, per person.

For each word that appears in at least MIN_WORD entries of the chosen calendars Bifrost measures:
* house_empty   – share of the entry time the house was away
* person_away / person_home – for people named in the title (names from the People tab)
* day_type      – the word mostly appears in all-day / multi-day entries (holidays, trips)
* missing       – on days with this word a routine happens much less often (e.g. "school" during holidays)

Privacy: only single words and counters are kept, never full titles. Words from the sensitive block
list (health, doctor …) are never learned and never shown. Names are matched, never stored as words.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta

MIN_WORD = 5
SENSITIVE = {
    "arzt", "ärztin", "doctor", "doc", "physio", "therapie", "therapy", "therapeut", "spital", "hospital", "klinik", "clinic",
    "zahnarzt", "dentist", "spritze", "injection", "medikament", "medication", "krank", "sick", "psychologe", "psychiater",
    "kur", "reha", "labor", "blut", "blood", "impfung", "vaccine", "pille", "pill", "frauenarzt", "gyn", "aimovig",
}  # fmt: skip
STOP = {
    "und",
    "mit",
    "der",
    "die",
    "das",
    "den",
    "dem",
    "des",
    "ein",
    "eine",
    "für",
    "fuer",
    "von",
    "bei",
    "beim",
    "zum",
    "zur",
    "uhr",
    "the",
    "and",
    "with",
    "for",
    "from",
    "evt",
    "was",
    "wegen",
    "neu",
}
WORD_RE = re.compile(r"[a-zäöüß]{3,}", re.IGNORECASE)


def words(title: str, blocked: set[str] | None = None) -> list[str]:
    blocked = SENSITIVE | (blocked or set())
    out = []
    for w in WORD_RE.findall(title or ""):
        w = w.lower()
        if w in STOP or w in blocked or any(b in w for b in blocked if len(b) >= 5):
            continue
        if w not in out:
            out.append(w)
    return out


def _dt(v, parse) -> datetime | None:  # noqa: ANN001
    if isinstance(v, dict):
        v = v.get("dateTime") or v.get("date")
    if not v:
        return None
    try:
        return parse(v)
    except Exception:  # noqa: BLE001
        return None


def _state_share(spans: list[tuple[datetime, str]], a: datetime, b: datetime, want: str) -> float | None:
    """Share of [a,b] during which the timeline (sorted (ts,state)) had state `want`."""
    if not spans or b <= a:
        return None
    total = (b - a).total_seconds()
    cur = None
    for t, s in spans:
        if t <= a:
            cur = s
    if cur is None and spans[0][0] > b:
        return None
    acc, pos, state = 0.0, a, cur
    for t, s in spans:
        if a < t < b:
            if state == want:
                acc += (t - pos).total_seconds()
            pos, state = t, s
    if state == want:
        acc += (b - pos).total_seconds()
    return acc / total


def learn(
    entries: dict[str, list[dict]],
    decisions: list[dict],
    person_timelines: dict[str, list[tuple[datetime, str]]],
    names: dict[str, str],
    parse,
    routine_days: dict[str, set] | None = None,
    blocked: set[str] | None = None,
) -> dict:  # noqa: ANN001
    """entries: calendar id → HA entries; names: lower-case name → person name; routine_days: goal → set of dates it happened."""
    house = sorted((parse(d["ts"]), d["state"]) for d in decisions)
    stats: dict[str, dict] = defaultdict(lambda: {"count": 0, "calendars": set(), "away": [], "allday": 0, "person": defaultdict(list), "days": set()})
    spans: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
    for cal, items in entries.items():
        for e in items:
            st, en = _dt(e.get("start"), parse), _dt(e.get("end"), parse)
            if not st or not en:
                continue
            title = e.get("summary") or ""
            allday = isinstance(e.get("start"), dict) and "date" in e["start"] and "dateTime" not in e["start"] or (en - st) >= timedelta(hours=20)
            who = [names[w.lower()] for w in WORD_RE.findall(title) if w.lower() in names]
            for w in words(title, blocked):
                if w in names:
                    continue  # names are matched, not learned as words
                s = stats[w]
                s["count"] += 1
                s["calendars"].add(cal)
                s["allday"] += 1 if allday else 0
                d = st
                while d.date() <= en.date():
                    s["days"].add(d.date())
                    d += timedelta(days=1)
                sh = _state_share(house, st, min(en, st + timedelta(hours=12)), "away")
                if sh is not None:
                    s["away"].append(sh)
                for p in who:
                    ps = _state_share(sorted(person_timelines.get(p, [])), st, min(en, st + timedelta(hours=12)), "away")
                    if ps is not None:
                        s["person"][p].append(ps)
                spans[w].append((st, en))
    out = {}
    for w, s in stats.items():
        if s["count"] < MIN_WORD:
            continue
        eff: dict = {}
        if s["away"]:
            eff["house_empty"] = round(sum(s["away"]) / len(s["away"]), 2)
        for p, v in s["person"].items():
            if len(v) >= 3:
                share = sum(v) / len(v)
                eff.setdefault("person", {})[p] = {"away": round(share, 2), "means": "away" if share >= 0.8 else "home" if share <= 0.2 else "mixed"}
        if s["allday"] / s["count"] >= 0.6:
            eff["day_type"] = True
        if routine_days:
            for goal, days in routine_days.items():
                if not days:
                    continue
                all_days = {d for dd in (days, s["days"]) for d in dd}
                with_word = s["days"] & all_days
                rate_with = len(days & with_word) / len(with_word) if with_word else None
                rate_without = len(days - s["days"]) / max(1, len(all_days - s["days"]))
                if rate_with is not None and rate_without >= 0.5 and rate_with <= 0.2 * rate_without:
                    eff.setdefault("missing", []).append(goal)
        out[w] = {"count": s["count"], "calendars": sorted(s["calendars"]), "effects": eff}
    return {"words": dict(sorted(out.items(), key=lambda x: -x[1]["count"])), "spans": {w: spans[w] for w in out}}


def active_words(entries_now: list[dict], learned: dict) -> list[str]:
    known = learned.get("words", {})
    found = []
    for e in entries_now:
        for w in words(e.get("summary") or ""):
            if w in known and w not in found:
                found.append(w)
    return found
