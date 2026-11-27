"""Brain (0.4–1.0) – connects pattern recognition, people, guard, questions and balance.

The service stays the HA/HTTP adapter; the brain holds the learned house model and runs the three
questions every minute:
  1. facts (entries, indoor motion, sleep/guest) → somebody is home
  2. guard (people accounted, unknowns, last out, data) → may it be empty?
  3. engine/patterns → how sure
"""

from __future__ import annotations

import base64
import logging
import threading
from collections import deque
from datetime import UTC, datetime, timedelta

from . import balance, blocks, calwords, guard, timing
from . import routines as rt
from .engine import AWAY, Decision, parse_time
from .location import Fingerprints, validate_floorplan
from .patterns import outcomes_from_decisions
from .people import STRENGTH_BY_INTEGRATION, WEAK, PeopleStore, ledger
from .questions import Inbox

LOG = logging.getLogger(__name__)
LEARN_DAYS = 56
LEARNING_PHASE_DAYS = 7
GOAL_OF = {"departure": "leaving", "arrival": "arriving", "bedtime": "sleep"}


def _p(v) -> datetime:  # noqa: ANN001
    return parse_time(v, datetime.now(UTC)) if not isinstance(v, datetime) else v


class Brain:
    def __init__(self, store, options: dict) -> None:  # noqa: ANN001
        self.store, self.options = store, options
        self.people = PeopleStore(store)
        self.inbox = Inbox(store)
        self.detector = blocks.Detector()
        self.gs = guard.GuardState()
        self.fingerprints = Fingerprints()
        self._lock = threading.Lock()
        self.identity: deque = deque(maxlen=200)  # recent identity events for explaining entries
        self.motion_last: datetime | None = None
        self.meta: dict[str, dict] = {}
        self.last_extra: dict = {}
        self._missing_reported: set[str] = set()
        saved = store.get_obj("model", "house") or {}
        self.detector.model = saved
        r = store.get_obj("model", "routines")
        self.routines: list[dict] = r["items"] if r else []
        self.words = store.get_obj("model", "calwords") or {"words": {}, "spans": {}}
        self.timing = store.get_obj("model", "timing") or {}

    # --- meta & identities ------------------------------------------------------------
    def set_meta(self, meta: dict[str, dict]) -> None:
        self.meta = meta

    def _tracker_owner(self) -> dict[str, tuple[str, str]]:
        out = {}
        for p in self.people.all():
            for t in p.sources:
                out[t] = (p.id, p.name)
        return out

    def strength(self, entity_id: str) -> str:
        integ = (self.meta.get(entity_id, {}).get("integration") or "").lower()
        return STRENGTH_BY_INTEGRATION.get(integ, WEAK)

    def on_edge(self, edge: dict) -> None:
        """Called for every clean edge from the live stream."""
        eid, kind = edge["entity_id"], edge["kind"]
        with self._lock:
            self.detector.feed(edge)
            m = self.meta.get(eid, {})
            if kind == "on" and m.get("category") == "motion" and self.detector.model.get("sides", {}).get(eid, {}).get("side") != "outside":
                self.motion_last = _p(edge["ts"])
            owner = self._tracker_owner().get(eid)
            if owner and kind == "home":
                self.identity.append({"ts": _p(edge["ts"]), "who": owner[1], "pid": owner[0], "kind": "home", "strength": self.strength(eid)})
            # NFC users at the alarm keypad (Loxone read-only, later): a change event whose value is a known NFC user
            if kind == "change" and m.get("category") == "security":
                for p in self.people.all():
                    if p.nfc_user and p.nfc_user.lower() in (edge.get("state") or "").lower():
                        self.identity.append({"ts": _p(edge["ts"]), "who": p.name, "pid": p.id, "kind": "nfc", "strength": "strong"})

    # --- every minute ---------------------------------------------------------------------
    def tick(self, d: Decision, states: dict[str, dict], now: datetime, guest_mode: bool) -> tuple[Decision, dict]:
        with self._lock:
            openings = self.detector.tick(now)
            level = int(self.options.get("suspicious_entry_level", 1))
            new_susp = []
            for o in openings:
                ts = _p(o["ts"])
                night = ts.astimezone().hour < 6
                exc = [x for x in self.inbox.exceptions() if x.get("door") == o["door"]]
                expl = guard.explain_entry(ts, list(self.identity), guest_mode, exc, night) if o["result"] == "entry" else {}
                before = self.last_extra.get("state_before", d.state)
                s = guard.on_opening(self.gs, o, expl, before, now, level)
                self._store_block_event(o, expl)
                if s:
                    new_susp.append(s)
                    facts = {"door": o["door"], "ts": o["ts"], "state_before": before, "too_weak": s["too_weak"]}
                    q = self.inbox.ask("suspicious_entry", f"{o['door']}|{o['ts'][:16]}", facts, now, safety=True)
                    self.inbox.deviation("unexplained", o["door"], facts, now, question=q["id"] if q else None)
            guard.tick(self.gs, now, self.motion_last)
            persons = self.people.all()
            simple_states = {k: v.get("state") for k, v in states.items()}
            led = ledger(persons, simple_states, {t: self.strength(t) for p in persons for t in p.sources}, self.gs.unknown_min)
            can_dir = any(e.get("direction") for e in self.detector.model.get("entrances", []))
            d2, checks = guard.apply(d, led, self.gs, now, can_dir)
            self._expected_missing(now)
            prog = self._in_progress(now)
            learning = self.learning_phase(now)
            extra = {
                "ledger": led,
                "checks": checks,
                "suspicion": self.gs.suspicion,
                "new_suspicions": new_susp,
                "openings": openings,
                "unknown_min": self.gs.unknown_min,
                "people_inside_min": self.detector.people_inside_min(now),
                "in_progress": prog,
                "learning": learning,
                "state_before": d2.state,
                "questions": self.inbox.counts(),
            }
            self.last_extra = extra
            return d2, extra

    def _store_block_event(self, o: dict, expl: dict) -> None:
        ts = _p(o["ts"])
        if o["result"] in ("entry", "exit", "inside_only"):
            self.store.add_event(ts, "bifrost.block", f"{o['result']} {o['door']}", "blocks", "Evidence", f"{o['result']}:{o['door']}", kind="block")
        if o["result"] == "entry" and expl.get("explained") and expl.get("who"):
            pid = next((x["pid"] for x in reversed(self.identity) if x["who"] == expl["who"]), None)
            if pid:
                self.store.add_event(ts, "bifrost.person", expl["who"], "people", "Evidence", f"{pid}:home", kind="person")
                st = self.store.get_obj("stats", "person_entries") or {}
                st[pid] = st.get(pid, 0) + 1
                self.store.put_obj("stats", "person_entries", st)

    def _in_progress(self, now: datetime) -> list[dict]:
        recent = [(_p(e["ts"]), tok) for e in self.store.events_since(now - rt.WINDOW, limit=3000) if (tok := rt.token_of(e))]
        out = []
        for p in self.routines:
            pr = rt.progress(p, recent, now)
            if 0.5 <= pr < 1:
                out.append({"id": p["id"], "goal": p["goal"], "progress": round(pr, 2), "who": p.get("who")})
        return out

    def _expected_missing(self, now: datetime) -> None:
        lt = now.astimezone()
        wd = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[lt.weekday()]
        for p in self.routines:
            c = p.get("conditions", {})
            if wd not in c.get("weekdays", []):
                continue
            to = c.get("time", {}).get("to")
            if not to:
                continue
            h, m = map(int, to.split(":"))
            end = lt.replace(hour=h, minute=m, second=0, microsecond=0) + timedelta(minutes=15)
            key = f"{p['id']}|{lt.date()}"
            if lt < end or key in self._missing_reported or lt - end > timedelta(hours=2):
                continue
            self._missing_reported.add(key)
            start = end - timedelta(hours=3)
            happened = any(GOAL_OF.get(p["goal"]) and x for x in self._outcomes_between(start, end, p["goal"]))
            if not happened:
                self.inbox.deviation("expected_missing", p["id"], {"routine": p["id"], "goal": p["goal"], "window": c.get("time")}, now)

    def _outcomes_between(self, a: datetime, b: datetime, goal: str) -> list:
        dec = self.store.decisions_since(a - timedelta(hours=1))
        return [t for g, t in outcomes_from_decisions(dec, _p) if g == goal and a <= t <= b]

    def learning_phase(self, now: datetime) -> dict:
        first = self.store.get_value("first_edge")
        days = (now - _p(first)).days if first else 0
        model = self.detector.model
        persons = self.people.all()
        items = [
            {"id": "days", "value": min(days, LEARNING_PHASE_DAYS), "need": LEARNING_PHASE_DAYS},
            {"id": "entrances", "value": sum(1 for e in model.get("entrances", []) if e.get("direction")), "need": max(1, len(model.get("doors", [])) and 1)},
            {"id": "people", "value": sum(1 for p in persons if p.sources), "need": max(1, len(persons))},
            {"id": "neighbours", "value": len(model.get("neighbours", [])), "need": 3},
        ]
        active = days < LEARNING_PHASE_DAYS or not any(e.get("direction") for e in model.get("entrances", []))
        return {"active": active, "items": items, "days": days}

    # --- nightly learning ----------------------------------------------------------------
    def learn(self, now: datetime, calendars: dict[str, list[dict]], duplicates: list[dict], current: dict[str, str | None]) -> dict:
        since = now - timedelta(days=LEARN_DAYS)
        events = list(reversed(self.store.events_since(since, limit=300000)))
        decisions = self.store.decisions_since(since)
        model = blocks.learn(events, self.meta, decisions)
        days = max(0.0, (now - _p(events[0]["ts"])).total_seconds() / 86400) if events else 0.0
        model["doctor"] = blocks.sensor_doctor(events, self.meta, days, current)
        persons = self.people.all()
        model["capability"] = blocks.capability(model, len(persons), sum(1 for p in persons if p.sources))
        with self._lock:
            self.detector.model = model
        self.store.put_obj("model", "house", model)
        # people timelines and names
        owners = self._tracker_owner()
        person_events = [(_p(e["ts"]), owners[e["entity_id"]][1], e["kind"]) for e in events if e["entity_id"] in owners and e["kind"] in ("home", "away")]
        timelines: dict[str, list] = {}
        for t, name, k in person_events:
            timelines.setdefault(name, []).append((t, "home" if k == "home" else "away"))
        names = {}
        for p in persons:
            for part in p.name.lower().split():
                if len(part) >= 3:
                    names[part] = p.name
        outs = outcomes_from_decisions(decisions, _p)
        routine_days: dict[str, set] = {}
        for g, t in outs:
            routine_days.setdefault(g, set()).add(t.astimezone().date())
        if self.options.get("learn_calendars", True) and calendars:
            self.words = calwords.learn(calendars, decisions, timelines, names, _p, routine_days)
            spans = self.words.pop("spans", {})
            self.store.put_obj("model", "calwords", {"words": self.words.get("words", {})})
        else:
            spans = {}
        tok_owner = {}
        for eid, (_pid, name) in owners.items():
            tok_owner[f"{eid}:home"] = tok_owner[f"{eid}:away"] = name
        for p in persons:
            tok_owner[f"person:{p.id}:home"] = p.name
        self.routines = rt.mine(events, outs, spans, tok_owner)
        self.store.put_obj("model", "routines", {"items": self.routines})
        self.timing = timing.learn(person_events)
        self.timing["_durations"] = timing.durations(decisions, _p)
        self.store.put_obj("model", "timing", self.timing)
        self._suggest(model, duplicates, now)
        self.inbox.expire(now)
        return {"entrances": len(model["entrances"]), "routines": len(self.routines), "words": len(self.words.get("words", {}))}

    def _suggest(self, model: dict, duplicates: list[dict], now: datetime) -> None:
        for dup in duplicates[:3]:
            self.inbox.ask("duplicate", f"{dup['a']}|{dup['b']}", dup, now)
        for door, role in model.get("roles", {}).items():
            if role.get("role") == "inside_only":
                self.inbox.ask("door_role", door, {"door": door, **role}, now)
        known = {x["sensor"] for x in self.inbox.exceptions()}
        for dist in model.get("disturbances", []):
            if dist["sensor"] not in known:
                self.inbox.ask("disturbance", dist["sensor"], dist, now)
        for prob in model.get("doctor", [])[:3]:
            self.inbox.ask("sensor_problem", f"{prob['entity_id']}|{prob['problem']}", prob, now)

    # --- answers & corrections -------------------------------------------------------------
    def answer(self, qid: str, answer: str, label: str | None, now: datetime, set_override) -> dict:  # noqa: ANN001
        q = self.inbox.answer(qid, answer, label, now)
        f, t = q.get("facts", {}), q["type"]
        if answer == "yes":
            if t == "duplicate":
                set_override(f["b"], "ignored", None, None)
            elif t == "disturbance":
                self.inbox.add_exception(f["sensor"], label or "disturbance")
                self.inbox.explain_deviations(f["sensor"], label)
            elif t == "sensor_problem":
                set_override(f["entity_id"], "ignored", None, None)
            elif t == "suspicious_entry":
                # "yes, that was us" – the unknown person is known after all
                self.gs.unknown_min = max(0, self.gs.unknown_min - 1)
                self.gs.suspicion = None
                self.inbox.explain_deviations(f.get("door", ""), label or "known")
                if label:
                    self.inbox.set_label("unexplained", f.get("door", ""), label)
            elif t == "door_role":
                self.store.put_obj("door_role", f["door"], {"door": f["door"], "role": f.get("role")})
        return q

    def correct(self, said: str, actual: str, now: datetime) -> dict:
        if actual not in ("home", "away", "asleep"):
            raise ValueError("actual must be home, away or asleep")
        lab = {"ts": now.isoformat(), "said": said, "actual": actual, "source": "owner"}
        self.store.put_obj("label", now.isoformat(), lab)
        if actual != AWAY:
            self.gs.unknown_min = max(self.gs.unknown_min, 0)
        return lab

    def labels(self) -> list[dict]:
        return [x for x in self.store.list_objs("label") if "said" in x]

    # --- views -----------------------------------------------------------------------------
    def house_view(self, names: dict[str, str]) -> dict:
        m = self.detector.model
        return {
            "map": m.get("map", {"nodes": [], "links": []}),
            "entrances": m.get("entrances", []),
            "sides": m.get("sides", {}),
            "roles": m.get("roles", {}),
            "doctor": m.get("doctor", []),
            "capability": m.get("capability", {}),
            "disturbances": m.get("disturbances", []),
            "exceptions": self.inbox.exceptions(),
            "names": {k: names.get(k, k) for k in {n["id"] for n in m.get("map", {}).get("nodes", [])}},
            "has_floorplan": bool(self.store.get_value("floorplan_type")),
        }

    def recognition_view(self, names: dict[str, str]) -> dict:
        """Blocks, people and routines in one nested format for the Pattern recognition tab."""
        m = self.detector.model
        items: dict[str, dict] = {}
        nm = lambda e: names.get(e, e)  # noqa: E731
        for en in m.get("entrances", []):
            if not en.get("inside"):
                continue
            role = m.get("roles", {}).get(en["door"], {})
            ein = [{"t": "opt", "label": nm(en["outside"]), "entity": en["outside"]}] if en.get("outside") else []
            items["in_" + en["door"]] = {
                "id": "in_" + en["door"], "type": "block", "goal": "arriving", "title": f"Entry via {nm(en['door'])}", "who": "house",
                "seen": role.get("entry", 0), "status": "active",
                "steps": ein + [{"t": "step", "label": nm(en["door"]), "entity": en["door"]}, {"t": "step", "label": nm(en["inside"]), "entity": en["inside"]}],
            }  # fmt: skip
            eout = [{"t": "opt", "label": nm(en["outside"]), "entity": en["outside"]}] if en.get("outside") else []
            items["out_" + en["door"]] = {
                "id": "out_" + en["door"], "type": "block", "goal": "leaving", "title": f"Exit via {nm(en['door'])}", "who": "house",
                "seen": role.get("exit", 0), "status": "active",
                "steps": [{"t": "step", "label": nm(en["inside"]), "entity": en["inside"]}, {"t": "step", "label": nm(en["door"]), "entity": en["door"]}, *eout,
                          {"t": "not", "label": "no motion inside", "minutes": blocks.EXIT_SILENCE // 60}],
            }  # fmt: skip
        for door, role in m.get("roles", {}).items():
            if role.get("role") == "inside_only":
                items["io_" + door] = {
                    "id": "io_" + door,
                    "type": "block",
                    "goal": "home",
                    "title": f"Opened from inside: {nm(door)}",
                    "who": "house",
                    "seen": role.get("inside_only", 0),
                    "status": "suggestion",
                    "steps": [{"t": "step", "label": "motion inside"}, {"t": "step", "label": nm(door), "entity": door}, {"t": "step", "label": "motion inside"}],
                }
        for x in self.inbox.exceptions():
            items["dist_" + x["sensor"]] = {
                "id": "dist_" + x["sensor"],
                "type": "block",
                "goal": "house",
                "title": f"Disturbance: {x.get('label')} at {nm(x['sensor'])}",
                "who": "house",
                "seen": 0,
                "status": "active",
                "steps": [{"t": "step", "label": nm(x["sensor"]) + " alone", "entity": x["sensor"]}, {"t": "not", "label": "no door, no neighbour", "minutes": 2}],
            }
        entries = [k for k in items if k.startswith("in_")]
        stats = self.store.get_obj("stats", "person_entries") or {}
        for p in self.people.all():
            if not p.sources:
                continue
            items["p_" + p.id] = {
                "id": "p_" + p.id, "type": "person", "goal": "arriving", "title": f"{p.name} comes home", "who": p.name, "seen": stats.get(p.id, 0), "status": "active",
                "steps": [{"t": "or", "items": [{"ref": k} for k in entries]}] if entries else [],
                "companions": [{"label": nm(t), "entity": t, "window": "−3…+2 min"} for t in p.sources],
            }  # fmt: skip
        for r in self.routines:
            steps = []
            for s in r["steps"]:
                its = []
                for tok in s["tokens"]:
                    if tok.startswith("block:"):
                        res, door = tok[6:].split(":", 1)
                        ref = ("in_" if res == "entry" else "out_" if res == "exit" else "io_") + door
                        its.append({"ref": ref} if ref in items else {"label": tok})
                    elif tok.startswith("person:"):
                        pid = tok.split(":")[1]
                        its.append({"ref": "p_" + pid} if "p_" + pid in items else {"label": tok})
                    else:
                        eid, k = tok.rsplit(":", 1)
                        its.append({"label": nm(eid) + ("" if k == "on" else f" → {k}"), "entity": eid})
                kind = {"step": "step", "optional": "opt", "and": "and", "or": "or"}[s["kind"]]
                if kind in ("step", "opt") and len(its) == 1:
                    steps.append({"t": kind, **its[0], "span": s.get("span")})
                else:
                    steps.append({"t": kind, "items": its, "span": s.get("span")})
            if r.get("not"):
                steps.append({"t": "not", "label": "no motion", "minutes": r["not"]["minutes"]})
            comps = [{"label": nm(c["token"].rsplit(":", 1)[0]), "entity": c["token"].rsplit(":", 1)[0], "window": f"{c['window']['from']}…{c['window']['to']} min"} for c in r.get("companions", [])]
            items[r["id"]] = {
                "id": r["id"], "type": "routine", "goal": GOAL_OF.get(r["goal"], r["goal"]), "title": r["goal"], "who": ", ".join(r.get("who") or ["family"]),
                "seen": r["seen"], "precision": r["precision"], "status": "active", "conditions": r.get("conditions"), "steps": steps, "companions": comps,
            }  # fmt: skip
        return {"items": list(items.values())}

    def balance_view(self, now: datetime, health: int, departures: int) -> dict:
        decisions = self.store.decisions_since(now - timedelta(days=30))
        sus = [q for q in self.inbox.all() if q["type"] == "suspicious_entry"]
        k = balance.kpis(self.labels(), decisions, [{"ts": q["ts"], "answer": q.get("answer")} for q in sus], now, _p)
        first = self.store.get_value("first_decision")
        g = balance.gate(_p(first) if first else None, departures, k, health, now)
        return {"kpis": k, "gate": g, "signal_option": bool(self.options.get("alarm_signal", False))}

    def floorplan(self, b64: str) -> None:
        data, ctype = validate_floorplan(b64)
        self.store.set_value("floorplan", base64.b64encode(data).decode())
        self.store.set_value("floorplan_type", ctype)

    def floorplan_bytes(self) -> tuple[bytes, str] | None:
        v, t = self.store.get_value("floorplan"), self.store.get_value("floorplan_type")
        return (base64.b64decode(v), t) if v and t else None
