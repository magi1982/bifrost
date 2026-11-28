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
import secrets
import threading
import time
from collections import deque
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from . import balance, baseline, blocks, calwords, corrections, evidence, guard, hindsight, house, timing, value
from . import routines as rt
from .engine import ASLEEP, AWAY, LEAVING, UNKNOWN, Decision, parse_time
from .floorplan import validate_floorplan
from .people import WEAK, PeopleStore, ledger, source_strength, visibility
from .questions import Inbox
from .routines import outcomes_from_decisions

LOG = logging.getLogger(__name__)
LEARN_DAYS = 56
LEARNING_PHASE_DAYS = 7
GOAL_OF = {"departure": "leaving", "arrival": "arriving", "bedtime": "sleep"}


def _sleep_window(bedtimes: list[datetime]) -> dict:
    """Usual bedtime (median of the learned ones, local time) to 8 hours later; default 22:30–06:30."""
    if len(bedtimes) < 3:
        return {"from": 22 * 60 + 30, "to": 6 * 60 + 30}
    mins = sorted((t.astimezone().hour * 60 + t.astimezone().minute + 720) % 1440 for t in bedtimes)  # noon-centred
    med = (mins[len(mins) // 2] - 720) % 1440
    return {"from": med, "to": (med + 480) % 1440}


def _p(v) -> datetime:  # noqa: ANN001
    return parse_time(v, datetime.now(UTC)) if not isinstance(v, datetime) else v


class Brain:
    def __init__(self, store, options: dict) -> None:  # noqa: ANN001
        self.store, self.options = store, options
        self.people = PeopleStore(store)
        self.people.migrate()
        self.inbox = Inbox(store)
        self.detector = blocks.Detector()
        self.gs = guard.GuardState.from_dict(store.get_obj("guard", "state"))
        self.started_at = datetime.now(UTC)
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
        self.evidence = store.get_obj("model", "evidence") or {}
        self.hind = store.get_obj("model", "hindsight") or {}
        self._last_pred: datetime | None = None
        self.baseline = store.get_obj("model", "baseline") or {}
        self.value = store.get_obj("model", "value") or {}
        self.paths = store.get_obj("model", "paths") or {"areas": [], "cells": []}
        self.last_door: datetime | None = None
        self._rare_seen: set[str] = set()
        self.last_openings: dict[str, dict] = {}

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
        wrong = self.corrections_effective()["trackers"].get(entity_id, 0)
        return WEAK if wrong >= 3 else source_strength(entity_id, self.meta.get(entity_id))

    def visibility(self, person) -> dict:  # noqa: ANN001
        return visibility(person, self.meta, self.corrections_effective()["trackers"])

    # --- corrections that fade (0.17) ------------------------------------------------------------
    def corrections_half_life(self) -> float:
        return corrections.half_life(corrections.progress(self.learn_status()["items"]))

    def corrections_effective(self, now: datetime | None = None) -> dict:
        """Faded weight of every owner correction: per signal, per tracker, and the labels that still count."""
        now = now or datetime.now(UTC)
        key = int(now.timestamp() // 60)
        if getattr(self, "_corr_cache", (None,))[0] == key:
            return self._corr_cache[1]
        trk = {p.id: list(p.trackers) for p in self.people.all()}
        labels = [lab if not lab.get("person") or lab.get("trackers") else {**lab, "trackers": trk.get(lab["person"], [])} for lab in self.labels()]
        eff = corrections.effective(labels, now, self.corrections_half_life(), _p)
        self._corr_cache = (key, eff)
        return eff

    def corrections_view(self, names: dict[str, str], now: datetime | None = None) -> dict:
        now = now or datetime.now(UTC)
        people = {p.id: p.name for p in self.people.all()}
        return corrections.view(self.labels(), now, self.corrections_half_life(), _p, names, people)

    def on_edge(self, edge: dict) -> None:
        """Called for every clean edge from the live stream."""
        eid, kind = edge["entity_id"], edge["kind"]
        with self._lock:
            self.detector.feed(edge)
            m = self.meta.get(eid, {})
            self._watch(edge, m)
            if kind == "on" and m.get("category") == "motion" and self.detector.model.get("sides", {}).get(eid, {}).get("side") != "outside":
                self.motion_last = _p(edge["ts"])
            owner = self._tracker_owner().get(eid)
            if owner and kind in ("home", "away"):
                self.identity.append({"ts": _p(edge["ts"]), "who": owner[1], "pid": owner[0], "kind": kind, "strength": self.strength(eid)})
            # access systems (keypad, NFC, fingerprint, smart lock): the service already resolved who it was
            if kind == "access":
                target = edge.get("state") or "unknown"
                ts = _p(edge["ts"])
                if target == "denied":
                    self.inbox.deviation("unexplained", f"access_denied:{eid}", {"sensor": eid, "detail": "access denied"}, ts)
                elif target != "ignore":
                    p = self.people.get(target) if target not in ("household", "unknown") else None
                    who = p.name if p else target
                    # a value nobody assigned is authorised but not yet confirmed by the owner: medium, not strong
                    strength = "medium" if target == "unknown" else "strong"
                    self.identity.append({"ts": ts, "who": who, "pid": p.id if p else None, "kind": "nfc", "strength": strength})
                    if p:
                        st = self.store.get_obj("stats", "access_users") or {}
                        st[p.id] = st.get(p.id, 0) + 1
                        self.store.put_obj("stats", "access_users", st)

    def _watch(self, edge: dict, m: dict) -> None:
        """Live detectors: rare moments (baseline) and indoor motion without entry while empty (contradiction)."""
        eid, kind, ts = edge["entity_id"], edge["kind"], _p(edge["ts"])
        cat = m.get("category")
        if kind == "on" and cat == "openings":
            self.last_door = ts
        if kind not in ("on", "access"):
            return
        exc = {x["sensor"] for x in self.inbox.exceptions()}
        bits = baseline.is_rare(self.baseline, eid, ts)
        if bits is not None and eid not in exc:
            key = f"{eid}|{ts.astimezone().date()}|{baseline.slot(ts)}"
            if key not in self._rare_seen:
                self._rare_seen.add(key)
                self.inbox.deviation("rare", key, {"sensor": eid, "ts": ts.isoformat(), "bits": bits}, ts)
        side = (self.detector.model.get("sides", {}).get(eid) or {}).get("side")
        if kind == "on" and cat == "motion" and side != "outside" and eid not in exc and self.last_extra.get("state_before") == AWAY and baseline.motion_without_entry(ts, self.last_door):
            self.inbox.deviation("contradiction", f"{eid}|{ts.isoformat()[:16]}", {"sensor": eid, "ts": ts.isoformat(), "detail": "motion inside without entry"}, ts)

    # --- every minute ---------------------------------------------------------------------
    def tick(self, d: Decision, states: dict[str, dict], now: datetime, guest_mode: bool) -> tuple[Decision, dict]:
        with self._lock:
            openings = self.detector.tick(now)
            level = int(self.options.get("suspicious_entry_level", 2))
            new_susp = []
            ids = list(self.identity)
            for o in openings:
                ts = _p(o["ts"])
                night = ts.astimezone().hour < 6
                exc = [x for x in self.inbox.exceptions() if x.get("door") == o["door"]]
                if o["result"] == blocks.DOOR_USED:
                    # quiet after the door is no proof – a phone leaving the zone confirms the exit
                    ex = guard.explain_exit(ts, ids)
                    if ex["explained"]:
                        o["result"] = "exit"
                        o["confirmed_by"] = "phone"
                self.last_openings[o["door"]] = {"result": o["result"], "at": now}
                if o["result"] == "entry":
                    expl = guard.explain_entry(ts, ids, guest_mode, exc, night)
                elif o["result"] == "exit":
                    expl = guard.explain_exit(ts, ids)
                else:
                    expl = {}
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
            vis = {p.id: self.visibility(p)["level"] for p in persons}
            for row in led["people"]:
                row["visibility"] = vis.get(row["id"])
            can_dir = any(e.get("direction") for e in self.detector.model.get("entrances", []))
            prob = self.probabilities(d, states, now)
            d = self._apply_evidence(d, prob)
            warming = now - self.started_at < guard.STARTUP_HOLD
            d2, checks = guard.apply(d, led, self.gs, now, can_dir, warming_up=warming)
            self.store.put_obj("guard", "state", self.gs.to_dict())
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
                "probabilities": prob,
            }
            self.last_extra = extra
            return d2, extra

    # --- evidence scale and probabilities (0.8) ---------------------------------------------
    def _predictions(self, now: datetime, days: int = 30) -> list[tuple[datetime, float]]:
        out = []
        for i in range(days):
            for row in (self.store.get_obj("pred", (now - timedelta(days=i)).date().isoformat()) or {}).get("rows", []):
                try:
                    out.append((_p(row[0]), float(row[1])))
                except (TypeError, ValueError, IndexError):
                    continue
        return out

    def unreliable(self) -> set[str]:
        return evidence.unreliable(self.evidence)

    def _sleep_likely(self, states: dict[str, dict], now: datetime) -> float:
        for eid, m in self.meta.items():
            if m.get("category") == "mode_home" and any(w in (eid + " " + (m.get("name") or "")).lower() for w in ("sleep", "schlaf", "night", "nacht", "bett", "bed")):
                if ((states.get(eid) or {}).get("state") or "").lower() == "on":
                    return 0.95
        sw = self.hind.get("sleep") or {"from": 22 * 60 + 30, "to": 6 * 60 + 30}
        local = now.astimezone()
        m = local.hour * 60 + local.minute
        inside = (sw["from"] <= m or m < sw["to"]) if sw["from"] > sw["to"] else sw["from"] <= m < sw["to"]
        if not inside:
            return 0.05
        quiet = self.motion_last is None or now - self.motion_last > timedelta(minutes=30)
        return 0.85 if quiet else 0.4

    def probabilities(self, d: Decision, states: dict[str, dict], now: datetime) -> dict:
        """Home / asleep / away in percent – from the evidence scale once it is ready, otherwise from the rules."""
        sleep = self._sleep_likely(states, now)
        if self.evidence.get("ready"):
            recent: dict[str, datetime] = {}
            for r in self.detector.recent:
                if r["entity_id"] not in recent or r["_t"] > recent[r["entity_id"]]:
                    recent[r["entity_id"]] = r["_t"]
            trackers = {s: (states.get(s) or {}).get("state") for s, w in (self.evidence.get("weights") or {}).items() if "home" in w}
            trackers = {s: ("home" if v == "home" else "away" if v not in (None, "", "unavailable", "unknown") else None) for s, v in trackers.items()}
            pr = evidence.predict(self.evidence, recent, trackers, now, self.corrections_effective(now)["culprits"])
            p_home, parts, source = pr["p_home"], pr["parts"], "evidence"
        else:
            c = d.confidence / 100
            p_home = {AWAY: 1 - c, UNKNOWN: 0.5}.get(d.state, c if d.state != LEAVING else 0.5)
            if d.state == ASLEEP:
                sleep = max(sleep, 0.9)
            parts, source = [], "rules"
        split = evidence.split_states(p_home, sleep)
        if self._last_pred is None or now - self._last_pred >= timedelta(minutes=15):
            self._last_pred = now
            day = now.date().isoformat()
            rows = (self.store.get_obj("pred", day) or {}).get("rows", [])
            self.store.put_obj("pred", day, {"rows": [*rows, [now.isoformat(), round(1 - p_home, 3), source]][-120:]})
        return {**split, "source": source, "parts": parts, "p_home": round(p_home, 4)}

    def _apply_evidence(self, d: Decision, prob: dict) -> Decision:
        """The scale may only make Bifrost more careful – never turn a rule decision into "empty"."""
        if prob.get("source") != "evidence" or d.state != AWAY:
            return d
        p_away = prob["away"]
        if p_away < 70:
            return replace(d, state=UNKNOWN, confidence=min(d.confidence, 60), reasons=[f"Evidence scale is not sure: {p_away} % empty", *d.reasons])
        return replace(d, confidence=min(d.confidence, p_away))

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

    def routine_progress(self, now: datetime) -> dict[str, float]:
        recent = [(_p(e["ts"]), tok) for e in self.store.events_since(now - rt.WINDOW, limit=3000) if (tok := rt.token_of(e))]
        return {p["id"]: round(rt.progress(p, recent, now), 2) for p in self.routines}

    def incidents_view(self, now: datetime) -> list[dict]:
        events = self.store.events_since(now - timedelta(days=14), limit=20000)
        return house.incidents(self.inbox.deviations(300), events, self.meta, (self.detector.model or {}).get("sides", {}), now)

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

    def learn_status(self) -> dict:
        """Learning progress: what is learned, what is almost there (for the card on the patterns tab)."""
        ev = self.evidence or {}
        n = ev.get("samples") or {}
        model = self.detector.model or {}
        return {
            "since": self.store.get_value("first_edge"),
            "updated": self.hind.get("updated"),
            "items": [
                {"id": "entrances", "value": sum(1 for e in model.get("entrances", []) if e.get("direction")), "need": max(1, len(model.get("doors", []))) if model.get("doors") else 1},
                {"id": "neighbours", "value": len(model.get("neighbours", [])), "need": 3},
                {"id": "routines", "value": len(self.routines), "need": 1},
                {"id": "words", "value": len(self.words.get("words", {})), "need": 1},
                {"id": "home_samples", "value": n.get("home", 0), "need": evidence.MIN_SAMPLES},
                {"id": "empty_samples", "value": n.get("empty", 0), "need": evidence.MIN_SAMPLES},
                {"id": "departures", "value": self.hind.get("departures", 0), "need": balance.GATE_DEPARTURES},
            ],
            "new": [{"id": r["id"], "goal": r["goal"], "first_seen": r.get("first_seen")} for r in self.routines if r.get("first_seen")],
        }

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
        # 0.8: the truth comes from hindsight facts and the owner – never from the live decision
        prev_sides = (self.detector.model or {}).get("sides", {})
        exceptions = {x["sensor"] for x in self.inbox.exceptions()}
        hind = hindsight.label(events, self.meta, prev_sides, exceptions, self.corrections_effective(now)["labels"])
        pseudo = hindsight.to_decisions(hind)
        model = blocks.learn(events, self.meta, pseudo)
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
        self.evidence = evidence.learn(events, hind, self.meta)
        self.value = value.judge(events, self.meta, self.evidence, model.get("doctor", []), duplicates, days)
        self.store.put_obj("model", "value", self.value)
        self.baseline = baseline.learn(events, self.meta)
        self.store.put_obj("model", "baseline", self.baseline)
        self.paths = baseline.paths(events, self.meta, model.get("sides", {}))
        self.store.put_obj("model", "paths", self.paths)
        self.store.put_obj("model", "evidence", self.evidence)
        bedtimes = [t for g, t in outcomes_from_decisions(decisions, _p) if g == "bedtime"]
        outs = [("departure", t) for t in hind["departures"]] + [("arrival", t) for t in hind["arrivals"]] + [("bedtime", t) for t in bedtimes]
        outs.sort(key=lambda x: x[1])
        recent = now - timedelta(days=3)
        self.hind = {
            "updated": now.isoformat(),
            "stats": hind["stats"],
            "departures": len(hind["departures"]),
            "disturbances": len(hind["disturbances"]),
            "wrong_empty": hindsight.wrong_empty(hind, decisions, _p)[-20:],
            "segments": [
                {"start": x["start"].isoformat(), "end": x["end"].isoformat(), "label": x["label"], "why": x["why"]} for x in hind["segments"] if x["end"] >= recent and x["why"] != "activity"
            ][-60:],
            "sleep": _sleep_window(bedtimes),
            "calibration": evidence.calibration(self._predictions(now), hind),
        }
        self.store.put_obj("model", "hindsight", self.hind)
        self._hind_full = hind
        routine_days: dict[str, set] = {}
        for g, t in outs:
            routine_days.setdefault(g, set()).add(t.astimezone().date())
        if self.options.get("learn_calendars", True) and calendars:
            self.words = calwords.learn(calendars, pseudo, timelines, names, _p, routine_days)
            spans = self.words.pop("spans", {})
            self.store.put_obj("model", "calwords", {"words": self.words.get("words", {})})
        else:
            spans = {}
        tok_owner = {}
        for eid, (_pid, name) in owners.items():
            tok_owner[f"{eid}:home"] = tok_owner[f"{eid}:away"] = name
        for p in persons:
            tok_owner[f"person:{p.id}:home"] = p.name
        self.routines = rt.stabilise(rt.mine(events, outs, spans, tok_owner), self.routines, now)
        self.store.put_obj("model", "routines", {"items": self.routines})
        self.timing = timing.learn(person_events)
        self.timing["_durations"] = timing.durations(decisions, _p)
        self.store.put_obj("model", "timing", self.timing)
        self._suggest(model, duplicates, now)
        self.inbox.expire(now)
        return {
            "entrances": len(model["entrances"]),
            "routines": len(self.routines),
            "words": len(self.words.get("words", {})),
            "empty_h": hind["stats"]["empty_h"],
            "evidence_ready": self.evidence.get("ready", False),
        }

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

    def correct(
        self,
        said: str,
        actual: str,
        now: datetime,
        culprit: str | None = None,
        person: str | None = None,
        person_said: str | None = None,
        parts: list[dict] | None = None,
        changed: list[str] | None = None,
    ) -> dict:
        """The owner says Bifrost was wrong – and only what is true. Bifrost works out the reason itself:

        * whole house: counted in the balance (a wrong "empty" blocks the alarm signal for 30 days),
        * the signals that pushed the decision the wrong way share the blame by how strongly they pushed
          (``parts`` – the evidence at that moment; without it the signals that just changed, ``changed``),
        * a person: that person's trackers lose reliability,
        * everything fades with time (see corrections.py) so Bifrost's own patterns take over.
        A signal blamed again and again on different days becomes a question (motion: disturbance).
        """
        if actual not in ("home", "away", "asleep"):
            raise ValueError("actual must be home, away or asleep")
        lab: dict = {"ts": now.isoformat(), "said": said, "actual": actual, "source": "owner"}
        learned: list[str] = []
        if person:
            p = self.people.get(person)
            if p is None:
                raise ValueError("unknown person")
            lab.update(person=p.id, said=person_said or said, trackers=list(p.trackers))
            if actual == "asleep":
                actual = lab["actual"] = "home"
            learned += [f"tracker:{t}" for t in p.trackers]
        elif said == "away" and actual in ("home", "asleep"):
            learned.append("balance:wrong_empty")
        elif said in ("home", "asleep", "arriving") and actual == "away":
            learned.append("balance:wrong_home")
        if culprit:  # older clients may still name one
            if not isinstance(culprit, str) or culprit not in self.meta:
                raise ValueError("unknown signal")
            blame = [{"entity_id": culprit, "share": 1.0}]
        elif person:
            blame = []
        else:
            blame = corrections.blame(lab["said"], actual, parts, [c for c in changed or [] if c in self.meta])
        if blame:
            lab["blame"] = blame
            learned += [f"trust:{b['entity_id']}" for b in blame]
        self.store.put_obj("label", f"{now.isoformat()}_{secrets.token_hex(3)}", {**lab, "learned": learned})
        self._corr_cache = (None, None)
        if not person and said == AWAY and actual != AWAY:
            # Bifrost said "empty" but somebody was there: somebody it does not know about is inside
            self.gs.unknown_min = max(self.gs.unknown_min, 1)
            self.store.put_obj("guard", "state", self.gs.to_dict())
            learned.append("guard:unknown")
        for eid in corrections.repeated(self.labels(), _p):
            if self.meta.get(eid, {}).get("category") == "motion" and any(b["entity_id"] == eid for b in blame):
                self.inbox.ask("disturbance", eid, {"sensor": eid, "count": corrections.ASK_TIMES}, now, priority=2)
                learned.append(f"question:{eid}")
        return {**lab, "learned": learned}

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
                "tkey": "rt_entry", "targs": {"door": nm(en["door"])},
                "seen": role.get("entry", 0), "status": "active",
                "steps": ein + [{"t": "step", "label": nm(en["door"]), "entity": en["door"]}, {"t": "step", "label": nm(en["inside"]), "entity": en["inside"]}],
            }  # fmt: skip
            eout = [{"t": "opt", "label": nm(en["outside"]), "entity": en["outside"]}] if en.get("outside") else []
            items["out_" + en["door"]] = {
                "id": "out_" + en["door"], "type": "block", "goal": "leaving", "title": f"Exit via {nm(en['door'])}", "who": "house",
                "tkey": "rt_exit", "targs": {"door": nm(en["door"])},
                "seen": role.get("exit", 0), "status": "active",
                "steps": [{"t": "step", "label": nm(en["inside"]), "entity": en["inside"]}, {"t": "step", "label": nm(en["door"]), "entity": en["door"]}, *eout,
                          {"t": "not", "label": "no motion inside", "lkey": "l_no_motion_inside", "minutes": blocks.EXIT_SILENCE // 60}],
            }  # fmt: skip
        for door, role in m.get("roles", {}).items():
            if role.get("role") == "inside_only":
                items["io_" + door] = {
                    "id": "io_" + door,
                    "type": "block",
                    "goal": "home",
                    "title": f"Opened from inside: {nm(door)}",
                    "tkey": "rt_inside",
                    "targs": {"door": nm(door)},
                    "who": "house",
                    "seen": role.get("inside_only", 0),
                    "status": "suggestion",
                    "steps": [
                        {"t": "step", "label": "motion inside", "lkey": "l_motion_inside"},
                        {"t": "step", "label": nm(door), "entity": door},
                        {"t": "step", "label": "motion inside", "lkey": "l_motion_inside"},
                    ],
                }
        dist_counts = {d["sensor"]: d["count"] for d in m.get("disturbances", [])}
        for x in self.inbox.exceptions():
            items["dist_" + x["sensor"]] = {
                "id": "dist_" + x["sensor"],
                "type": "block",
                "goal": "house",
                "title": f"Disturbance: {x.get('label')} at {nm(x['sensor'])}",
                "tkey": "rt_dist",
                "targs": {"label": x.get("label") or "", "sensor": nm(x["sensor"])},
                "who": "house",
                "seen": dist_counts.get(x["sensor"], 0),
                "status": "active",
                "steps": [
                    {"t": "step", "label": nm(x["sensor"]) + " alone", "lkey": "l_alone", "largs": {"x": nm(x["sensor"])}, "entity": x["sensor"]},
                    {"t": "not", "label": "no door, no neighbour", "lkey": "l_no_door_neighbour", "minutes": 2},
                ],
            }
        entries = [k for k in items if k.startswith("in_")]
        stats = self.store.get_obj("stats", "person_entries") or {}
        for p in self.people.all():
            if not p.sources:
                continue
            items["p_" + p.id] = {
                "id": "p_" + p.id, "type": "person", "goal": "arriving", "title": f"{p.name} comes home", "who": p.name, "seen": stats.get(p.id, 0), "status": "active",
                "tkey": "rt_person", "targs": {"name": p.name},
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
                    elif tok.startswith("access:"):
                        _, eid, target = tok.split(":", 2)
                        p = self.people.get(target) if target not in ("household", "unknown") else None
                        who = p.name if p else {"household": "Household", "unknown": "authorised"}.get(target, target)
                        its.append({"label": f"{nm(eid)} · {who}", "entity": eid})
                    elif tok.startswith("person:"):
                        pid = tok.split(":")[1]
                        its.append({"ref": "p_" + pid} if "p_" + pid in items else {"label": tok})
                    else:
                        eid, k = tok.rsplit(":", 1)
                        its.append({"label": nm(eid) + ("" if k == "on" else f" → {k}"), "entity": eid})
                kind = {"step": "step", "optional": "opt", "and": "and", "or": "or"}[s["kind"]]
                share = round(s.get("share", 0), 2) if s.get("share") is not None else None
                if kind in ("step", "opt") and len(its) == 1:
                    steps.append({"t": kind, **its[0], "span": s.get("span"), "share": share})
                else:
                    steps.append({"t": kind, "items": its, "span": s.get("span"), "share": share})
            if r.get("not"):
                steps.append({"t": "not", "label": "no motion", "lkey": "l_no_motion", "minutes": r["not"]["minutes"], "share": r["not"].get("share")})
            comps = [
                {"label": nm(c["token"].rsplit(":", 1)[0]), "entity": c["token"].rsplit(":", 1)[0], "window": f"{c['window']['from']}…{c['window']['to']} min", "share": c.get("share")}
                for c in r.get("companions", [])
            ]
            items[r["id"]] = {
                "id": r["id"], "type": "routine", "goal": GOAL_OF.get(r["goal"], r["goal"]), "title": r["goal"], "who": ", ".join(r.get("who") or ["family"]),
                "seen": r["seen"], "precision": r["precision"], "status": "active", "conditions": r.get("conditions"), "steps": steps, "companions": comps,
            }  # fmt: skip
        sigs = sorted(((v.get("total", 0), k) for k, v in (self.baseline.get("signals") or {}).items()), reverse=True)[:16]
        heat = {k: baseline.heat(self.baseline, k) for _, k in sigs}
        return {"items": list(items.values()), "baseline": heat, "paths": self.paths, "learn": self.learn_status()}

    def balance_view(self, now: datetime, health: int, departures: int) -> dict:
        decisions = self.store.decisions_since(now - timedelta(days=30))
        sus = [q for q in self.inbox.all() if q["type"] == "suspicious_entry"]
        k = balance.kpis(self.labels(), decisions, [{"ts": q["ts"], "answer": q.get("answer")} for q in sus], now, _p)
        # hindsight is the backtest: "empty" while somebody was certainly inside counts like an owner's correction
        since = (now - timedelta(days=30)).isoformat()
        k["wrong_empty_hindsight"] = sum(1 for w in self.hind.get("wrong_empty", []) if w.get("from", "") >= since)
        k["wrong_empty"] += k["wrong_empty_hindsight"]
        first = self.store.get_value("first_decision")
        household = sum(1 for p in self.people.all() if p.kind == "household")
        g = balance.gate(_p(first) if first else None, departures, k, health, now, household)
        return {
            "kpis": k,
            "gate": g,
            "signal_option": bool(self.options.get("alarm_signal", False)),
            "hindsight": {x: self.hind.get(x) for x in ("updated", "stats", "departures", "disturbances", "wrong_empty", "calibration")},
            "evidence": {"ready": bool(self.evidence.get("ready")), "samples": self.evidence.get("samples", {}), "min": evidence.MIN_SAMPLES},
        }

    def has_floorplan(self, key: str = "") -> bool:
        """Cheap check (cached): the live view asks this for every floor and picture every few seconds."""
        cache = self.__dict__.setdefault("_fp_has", {})
        if key not in cache:
            cache[key] = bool(self.store.get_value("floorplan_type" + (f":{key}" if key else "")))
        return cache[key]

    def floorplan_version(self, key: str = "") -> str:
        """Changes with every upload – part of the picture URL so the browser can cache it."""
        cache = self.__dict__.setdefault("_fp_v", {})
        if key not in cache:
            cache[key] = self.store.get_value("floorplan_v" + (f":{key}" if key else "")) or "1"
        return cache[key]

    def floorplan(self, b64: str, key: str = "") -> None:
        """Store a floor plan picture – one per floor (key from house.floor_key), "" = the single legacy plan."""
        data, ctype = validate_floorplan(b64)
        suffix = f":{key}" if key else ""
        self.store.set_value("floorplan" + suffix, base64.b64encode(data).decode())
        self.store.set_value("floorplan_type" + suffix, ctype)
        self.store.set_value("floorplan_v" + suffix, str(int(time.time())))
        self.__dict__.setdefault("_fp_has", {})[key] = True
        self.__dict__.setdefault("_fp_v", {}).pop(key, None)

    def floorplan_bytes(self, key: str = "") -> tuple[bytes, str] | None:
        suffix = f":{key}" if key else ""
        v, t = self.store.get_value("floorplan" + suffix), self.store.get_value("floorplan_type" + suffix)
        return (base64.b64decode(v), t) if v and t else None

    def delete_floorplan(self, key: str) -> None:
        for k in (f"floorplan:{key}", f"floorplan_type:{key}"):
            self.store.set_value(k, "")
        self.__dict__.setdefault("_fp_has", {})[key] = False
