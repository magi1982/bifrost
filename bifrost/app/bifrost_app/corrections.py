"""The owner's "That's wrong" – one tap, Bifrost finds the reason itself, and corrections fade (0.17).

* **One tap**: the owner only says what is true (home / away / asleep). Nobody is asked who or what caused it.
* **Blame by share**: the signals that pushed the decision towards the wrong state at that moment share the blame
  by how strongly they pushed (evidence parts). Without an evidence model yet, the signals that changed in the
  last minutes before the correction share it equally.
* **Fading**: a correction counts ``½^(age / half-life)``. The half-life is long while Bifrost has learned little by
  itself (``HL_MAX`` days) and shortens to ``HL_MIN`` days once the learning progress is full – then Bifrost's own
  patterns take over. Under ``FLOOR`` a correction no longer counts for learning (it stays in the history).
* **Questions** only when the same signal keeps being blamed on different days.

The release gate ("0 wrong empty in 30 days") does not use the fading weights – safety stays strict.
"""

from __future__ import annotations

from datetime import datetime

HL_MAX, HL_MIN = 30.0, 7.0  # days
FLOOR = 0.1
MIN_SHARE = 0.1
ASK_TIMES, ASK_SHARE = 3, 0.3  # blamed this often (on different days) with at least this share → ask

TOWARDS_HOME = ("home", "asleep", "arriving", "leaving")


def half_life(progress: float) -> float:
    """Days a correction keeps half its weight; progress 0..1 is Bifrost's own learning progress."""
    p = max(0.0, min(1.0, progress))
    return round(HL_MAX - (HL_MAX - HL_MIN) * p, 1)


def progress(items: list[dict]) -> float:
    """Mean of value/need over the learning-progress items."""
    ratios = [min(1.0, it.get("value", 0) / max(1, it.get("need", 1))) for it in items or []]
    return sum(ratios) / len(ratios) if ratios else 0.0


def fade(ts: datetime, now: datetime, hl: float) -> float:
    age = max(0.0, (now - ts).total_seconds() / 86400)
    w = 0.5 ** (age / max(0.5, hl))
    return round(w, 3) if w >= FLOOR else 0.0


def blame(said: str, actual: str, parts: list[dict] | None, changed: list[str] | None = None) -> list[dict]:
    """Who pushed the decision the wrong way, as shares that add up to 1.

    parts: evidence parts at that moment ({entity_id, weight}); positive weight pushes towards "somebody home".
    changed: signals that changed shortly before (used when there are no parts).
    """
    said_home = said in TOWARDS_HOME
    actual_home = actual in ("home", "asleep")
    if said_home == actual_home:
        return []  # e.g. "asleep" instead of "home": nobody pushed the wrong way about presence
    wrong = [(p["entity_id"], abs(float(p.get("weight") or 0))) for p in parts or [] if p.get("entity_id") and (float(p.get("weight") or 0) > 0) == said_home and p.get("weight")]
    total = sum(w for _, w in wrong)
    if total > 0:
        out = [{"entity_id": e, "share": round(w / total, 2)} for e, w in sorted(wrong, key=lambda x: -x[1])]
    else:
        uniq = list(dict.fromkeys(changed or []))[:6]
        out = [{"entity_id": e, "share": round(1 / len(uniq), 2)} for e in uniq] if uniq else []
    return [b for b in out if b["share"] >= MIN_SHARE]


def effective(labels: list[dict], now: datetime, hl: float, parse) -> dict:  # noqa: ANN001
    """Faded weights: per signal (house corrections), per tracker (person corrections), and the owner labels that still
    count for hindsight (each with its weight "_w")."""
    culprits: dict[str, float] = {}
    trackers: dict[str, float] = {}
    keep: list[dict] = []
    for lab in labels:
        try:
            w = fade(parse(lab["ts"]), now, hl)
        except (KeyError, ValueError, TypeError):
            continue
        if w <= 0:
            continue
        if lab.get("person"):
            for t in lab.get("trackers") or []:
                trackers[t] = round(trackers.get(t, 0.0) + w, 3)
        else:
            keep.append({**lab, "_w": w})
        items = lab.get("blame") or ([{"entity_id": lab["culprit"], "share": 1.0}] if lab.get("culprit") else [])
        for b in items:
            culprits[b["entity_id"]] = round(culprits.get(b["entity_id"], 0.0) + w * b["share"], 3)
    return {"culprits": culprits, "trackers": trackers, "labels": keep}


def repeated(labels: list[dict], parse) -> list[str]:  # noqa: ANN001
    """Signals blamed with a real share on at least ASK_TIMES different days."""
    days: dict[str, set] = {}
    for lab in labels:
        try:
            d = parse(lab["ts"]).date()
        except (KeyError, ValueError, TypeError):
            continue
        for b in lab.get("blame") or []:
            if b.get("share", 0) >= ASK_SHARE:
                days.setdefault(b["entity_id"], set()).add(d)
    return sorted(e for e, ds in days.items() if len(ds) >= ASK_TIMES)


def view(labels: list[dict], now: datetime, hl: float, parse, names: dict[str, str], people: dict[str, str]) -> dict:  # noqa: ANN001
    """How often Bifrost was wrong, how much each correction still counts, and which signals fooled it most."""
    items, signals = [], {}
    month = 0
    for lab in sorted(labels, key=lambda x: x.get("ts", ""), reverse=True):
        try:
            t = parse(lab["ts"])
        except (KeyError, ValueError, TypeError):
            continue
        w = fade(t, now, hl)
        if (now - t).days < 30:
            month += 1
        bl = lab.get("blame") or ([{"entity_id": lab["culprit"], "share": 1.0}] if lab.get("culprit") else [])
        for b in bl:
            s = signals.setdefault(b["entity_id"], {"entity_id": b["entity_id"], "name": names.get(b["entity_id"], b["entity_id"]), "times": 0, "score": 0.0})
            s["times"] += 1
            s["score"] = round(s["score"] + w * b["share"], 2)
        if len(items) < 15:
            items.append(
                {
                    "ts": lab["ts"],
                    "said": lab.get("said"),
                    "actual": lab.get("actual"),
                    "person": people.get(lab.get("person") or "", lab.get("person")),
                    "weight": w,
                    "blame": [{"name": names.get(b["entity_id"], b["entity_id"]), "share": b["share"]} for b in bl[:3]],
                }
            )
    top = sorted(signals.values(), key=lambda s: (-s["score"], -s["times"]))[:8]
    return {"total": len(labels), "month": month, "half_life": hl, "items": items, "signals": top}
