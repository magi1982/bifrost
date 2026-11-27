"""Deviations, questions and suggestions (0.4/0.6).

* A **deviation** is a moment that did not fit (four generic kinds only):
  expected_missing · unexplained · rare · contradiction.
* A **question** asks the owner about something Bifrost cannot resolve alone; a **suggestion** proposes
  a change (merge duplicate sensors, door role, known disturbance, sensor problem).
* Answers: yes / no / maybe / dontknow (+ optional label). "dontknow" keeps the case waiting and
  re-asks only when the same thing happens again; otherwise it expires.
* Budget: few new items per day, ranked by value; similar items are grouped by a key.

No hand-written special cases: texts are built from the facts; labels come from the owner.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta

KIND_Q, KIND_DEV, KIND_EXC, KIND_LABEL = "question", "deviation", "exception", "label"
ANSWERS = ("yes", "no", "maybe", "dontknow")
DEV_KINDS = ("expected_missing", "unexplained", "rare", "contradiction")
Q_TYPES = ("suspicious_entry", "duplicate", "door_role", "disturbance", "sensor_problem", "deviation")
SUGGESTION_TYPES = ("duplicate", "door_role", "disturbance", "sensor_problem")
DAILY_BUDGET = {"question": 3, "suggestion": 5}
EXPIRE = timedelta(days=7)
LABEL_RE = re.compile(r"^[\w .,'\-]{1,40}$", re.UNICODE)


def qid(qtype: str, key: str) -> str:
    return qtype + "_" + hashlib.sha1(key.encode(), usedforsecurity=False).hexdigest()[:10]


def category(qtype: str) -> str:
    return "suggestion" if qtype in SUGGESTION_TYPES else "question"


class Inbox:
    def __init__(self, store) -> None:  # noqa: ANN001
        self.store = store

    # --- questions & suggestions ---------------------------------------------
    def all(self) -> list[dict]:
        return sorted(self.store.list_objs(KIND_Q), key=lambda q: (q["status"] != "open", -q.get("priority", 0), q["ts"]))

    def open_items(self) -> list[dict]:
        return [q for q in self.all() if q["status"] == "open"]

    def _created_today(self, cat: str, now: datetime) -> int:
        day = now.date().isoformat()
        return sum(1 for q in self.store.list_objs(KIND_Q) if q.get("category") == cat and q["ts"][:10] == day)

    def ask(self, qtype: str, key: str, facts: dict, now: datetime, priority: int = 1, safety: bool = False) -> dict | None:
        """Create (or refresh) a question. Respects the daily budget except for safety questions."""
        if qtype not in Q_TYPES:
            raise ValueError("unknown question type")
        oid = qid(qtype, key)
        cur = self.store.get_obj(KIND_Q, oid)
        if cur:
            if cur["status"] == "answered" and cur.get("answer") in ("yes", "no"):
                return None  # already decided – never ask again
            cur["count"] = cur.get("count", 1) + 1
            cur["facts"] = facts
            cur["last"] = now.isoformat()
            if cur["status"] in ("waiting", "expired"):
                cur["status"] = "open"  # it happened again → ask again
            self.store.put_obj(KIND_Q, oid, cur)
            return cur
        cat = category(qtype)
        if not safety and self._created_today(cat, now) >= DAILY_BUDGET[cat]:
            return None
        q = {
            "id": oid,
            "type": qtype,
            "category": cat,
            "key": key,
            "facts": facts,
            "ts": now.isoformat(),
            "last": now.isoformat(),
            "status": "open",
            "priority": priority + (10 if safety else 0),
            "count": 1,
            "safety": safety,
        }
        self.store.put_obj(KIND_Q, oid, q)
        return q

    def answer(self, oid: str, answer: str, label: str | None, now: datetime) -> dict:
        if answer not in ANSWERS:
            raise ValueError("answer must be yes, no, maybe or dontknow")
        if label is not None and label != "" and (not isinstance(label, str) or not LABEL_RE.match(label)):
            raise ValueError("label: up to 40 letters, digits, space . , ' -")
        q = self.store.get_obj(KIND_Q, oid) if isinstance(oid, str) else None
        if not q:
            raise ValueError("unknown question")
        q.update(answer=answer, label=(label or None), answered=now.isoformat(), status="waiting" if answer == "dontknow" else "answered")
        self.store.put_obj(KIND_Q, oid, q)
        return q

    def expire(self, now: datetime) -> int:
        n = 0
        for q in self.store.list_objs(KIND_Q):
            if q["status"] in ("open", "waiting") and not q.get("safety") and now - datetime.fromisoformat(q["last"]) > EXPIRE:
                q["status"] = "expired"
                self.store.put_obj(KIND_Q, q["id"], q)
                n += 1
        return n

    def counts(self) -> dict:
        items = self.store.list_objs(KIND_Q)
        return {c: sum(1 for q in items if q["status"] == "open" and q["category"] == c) for c in ("question", "suggestion")}

    # --- deviations -----------------------------------------------------------
    def deviation(self, kind: str, key: str, facts: dict, now: datetime, question: str | None = None) -> dict:
        if kind not in DEV_KINDS:
            raise ValueError("unknown deviation kind")
        oid = "dev_" + hashlib.sha1(f"{kind}|{key}|{now.isoformat()[:16]}".encode(), usedforsecurity=False).hexdigest()[:12]
        label = self.label_for(kind, key)
        d = {"id": oid, "kind": kind, "key": key, "facts": facts, "ts": now.isoformat(), "status": "explained" if label else "open", "label": label, "question": question}
        self.store.put_obj(KIND_DEV, oid, d)
        return d

    def deviations(self, limit: int = 100) -> list[dict]:
        return sorted(self.store.list_objs(KIND_DEV), key=lambda d: d["ts"], reverse=True)[:limit]

    def explain_deviations(self, key: str, label: str | None) -> None:
        for d in self.store.list_objs(KIND_DEV):
            if d["key"] == key and d["status"] == "open":
                d.update(status="explained", label=label)
                self.store.put_obj(KIND_DEV, d["id"], d)

    # --- owner labels: same structure next time → same name -------------------
    def set_label(self, kind: str, key: str, label: str) -> None:
        self.store.put_obj(KIND_LABEL, f"{kind}|{key}", {"kind": kind, "key": key, "label": label})

    def label_for(self, kind: str, key: str) -> str | None:
        d = self.store.get_obj(KIND_LABEL, f"{kind}|{key}")
        return d["label"] if d else None

    # --- narrow exceptions (known disturbances) --------------------------------
    def exceptions(self) -> list[dict]:
        return self.store.list_objs(KIND_EXC)

    def add_exception(self, sensor: str, label: str | None) -> None:
        self.store.put_obj(KIND_EXC, sensor, {"sensor": sensor, "kind": "isolated", "label": label or "disturbance"})

    def remove_exception(self, sensor: str) -> bool:
        return self.store.del_obj(KIND_EXC, sensor)
