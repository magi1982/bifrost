"""Pattern mining v0.3 – recurring step-by-step processes before a change of the home state.

Bifrost looks at what happened in the 60 minutes before every departure (Home → Leaving/Away),
arrival (Away → Arriving/Home) and bedtime (→ Asleep). Steps that appear in the same order
again and again become a *pattern*, e.g.

    calendar "Work" starts  →  ~12 min  →  front door opens  →  ~3 min  →  iPhone leaves  ⇒  departure

A pattern is suggested when it was seen at least MIN_SUPPORT times and, whenever its steps
happened, the outcome followed in at least MIN_PRECISION of the cases.
Everything runs locally on the stored events; nothing leaves the device.
"""

from __future__ import annotations

import hashlib
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import combinations

WINDOW = timedelta(minutes=60)  # look-back before an outcome
FOLLOW = timedelta(minutes=30)  # an outcome must follow the last step within this time
MIN_SUPPORT = 5
MIN_PRECISION = 0.85
MAX_STEPS = 5
MAX_TOKENS = 10  # only the most frequent steps are combined (keeps mining fast)
ACTIVE_STATES = {"on", "open", "unlocked", "playing", "detected", "occupied"}
OUTCOMES = {"departure": "Leaving home", "arrival": "Coming home", "bedtime": "Going to sleep"}


def step_token(entity_id: str, state: str) -> str | None:
    """Only meaningful transitions become steps."""
    st = (state or "").lower()
    if entity_id.startswith(("person.", "device_tracker.")):
        return f"{entity_id}:{'home' if st == 'home' else 'away'}"
    if st in ACTIVE_STATES:
        return f"{entity_id}:on"
    return None


def outcomes_from_decisions(decisions: list[dict], parse) -> list[tuple[str, datetime]]:  # noqa: ANN001
    out: list[tuple[str, datetime]] = []
    prev = None
    for d in decisions:
        s, t = d["state"], parse(d["ts"])
        if prev in ("home", "asleep") and s in ("leaving", "away"):
            out.append(("departure", t))
        elif prev == "away" and s in ("arriving", "home"):
            out.append(("arrival", t))
        elif prev in ("home", "arriving") and s == "asleep":
            out.append(("bedtime", t))
        prev = s
    return out


@dataclass
class Pattern:
    id: str
    outcome: str
    tokens: list[str]
    support: int
    occurrences: int
    precision: float
    gaps: list[int]  # median minutes between consecutive steps
    lead: int  # median minutes from last step to the outcome
    names: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        steps = []
        for i, tok in enumerate(self.tokens):
            eid, state = tok.rsplit(":", 1)
            steps.append({"entity_id": eid, "state": state, "name": self.names.get(eid, eid), "gap_before": self.gaps[i - 1] if i else None})
        return {
            "id": self.id,
            "outcome": self.outcome,
            "outcome_label": OUTCOMES[self.outcome],
            "steps": steps,
            "support": self.support,
            "occurrences": self.occurrences,
            "precision": round(100 * self.precision),
            "lead": self.lead,
        }


def _pid(outcome: str, tokens: list[str]) -> str:
    return hashlib.sha1((outcome + "|" + "|".join(tokens)).encode(), usedforsecurity=False).hexdigest()[:10]


def _ordered_times(seq: list[tuple[datetime, str]], tokens: tuple[str, ...]) -> list[datetime] | None:
    """Times of tokens appearing in this order in seq (greedy, latest-possible match for the last step)."""
    times: list[datetime] = []
    i = 0
    for tok in tokens:
        while i < len(seq) and seq[i][1] != tok:
            i += 1
        if i == len(seq):
            return None
        times.append(seq[i][0])
        i += 1
    return times


def mine(events: list[dict], decisions: list[dict], parse, names: dict[str, str] | None = None) -> list[Pattern]:  # noqa: ANN001, C901
    """events/decisions as stored (any order); parse = ISO string -> datetime."""
    names = names or {}
    seq = sorted((parse(e["ts"]), tok) for e in events if (tok := step_token(e["entity_id"], e["state"])))
    if not seq:
        return []
    found: list[Pattern] = []
    outs = outcomes_from_decisions(sorted(decisions, key=lambda d: d["ts"]), parse)
    for outcome in OUTCOMES:
        hits = [t for o, t in outs if o == outcome]
        if len(hits) < MIN_SUPPORT:
            continue
        windows = [[(t, tok) for t, tok in seq if h - WINDOW <= t <= h] for h in hits]
        # tokens that appear before enough outcomes (Apriori level 1)
        freq: dict[str, int] = {}
        for w in windows:
            for tok in {tok for _, tok in w}:
                freq[tok] = freq.get(tok, 0) + 1
        top = [t for t, n in sorted(freq.items(), key=lambda x: -x[1]) if n >= MIN_SUPPORT][:MAX_TOKENS]
        if len(top) < 2:
            continue
        # typical order: median offset before the outcome
        offs = {tok: statistics.median([(h - t).total_seconds() for w, h in zip(windows, hits, strict=True) for t, x in w if x == tok]) for tok in top}
        for n in range(min(MAX_STEPS, len(top)), 1, -1):
            for combo in combinations(sorted(top, key=lambda x: -offs[x]), n):
                matches = []
                for w, h in zip(windows, hits, strict=True):
                    ts = _ordered_times(w, combo)
                    if ts and h - ts[-1] <= FOLLOW:
                        matches.append((ts, h))
                if len(matches) < MIN_SUPPORT:
                    continue
                # precision: how often the same ordered steps (within the window span) led to the outcome
                occ = _count_occurrences(seq, combo)
                precision = len(matches) / max(occ, len(matches))
                if precision < MIN_PRECISION:
                    continue
                gaps = [round(statistics.median([(ts[i + 1] - ts[i]).total_seconds() / 60 for ts, _ in matches])) for i in range(n - 1)]
                lead = round(statistics.median([(h - ts[-1]).total_seconds() / 60 for ts, h in matches]))
                found.append(
                    Pattern(
                        _pid(outcome, list(combo)),
                        outcome,
                        list(combo),
                        len(matches),
                        occ,
                        precision,
                        gaps,
                        lead,
                        {tok.rsplit(":", 1)[0]: names.get(tok.rsplit(":", 1)[0], tok.rsplit(":", 1)[0]) for tok in combo},
                    )
                )
    return _keep_maximal(found)


def _count_occurrences(seq: list[tuple[datetime, str]], combo: tuple[str, ...]) -> int:
    """Non-overlapping occurrences of the ordered steps within WINDOW anywhere in the history."""
    wanted = set(combo)
    seq = [x for x in seq if x[1] in wanted]
    count, i = 0, 0
    while i < len(seq):
        if seq[i][1] != combo[0]:
            i += 1
            continue
        start = seq[i][0]
        j, k = i + 1, 1
        while j < len(seq) and k < len(combo) and seq[j][0] - start <= WINDOW:
            if seq[j][1] == combo[k]:
                k += 1
            j += 1
        if k == len(combo):
            count += 1
            i = j
        else:
            i += 1
    return count


def _keep_maximal(pats: list[Pattern]) -> list[Pattern]:
    """Drop a pattern if a longer one of the same outcome contains all its steps in order."""
    keep = []
    for p in pats:
        sub = any(q is not p and q.outcome == p.outcome and len(q.tokens) > len(p.tokens) and _is_subseq(p.tokens, q.tokens) and q.support >= p.support for q in pats)
        if not sub:
            keep.append(p)
    return sorted(keep, key=lambda p: (-p.precision, -p.support))


def _is_subseq(a: list[str], b: list[str]) -> bool:
    it = iter(b)
    return all(x in it for x in a)


def progress(pattern_tokens: list[str], recent: list[tuple[datetime, str]], now: datetime) -> int:
    """How many leading steps of a pattern happened (in order) within the last WINDOW."""
    seq = [(t, tok) for t, tok in sorted(recent) if now - t <= WINDOW]
    best = 0
    for k in range(len(pattern_tokens), 0, -1):
        if _ordered_times(seq, tuple(pattern_tokens[:k])):
            best = k
            break
    return best
