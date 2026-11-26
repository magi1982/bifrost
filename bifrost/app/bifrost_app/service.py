"""Core loop: scan Home Assistant, classify entities, decide, publish."""

from __future__ import annotations

import logging
import re
import statistics
import threading
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta

from . import __version__
from . import calendars as cal
from . import patterns as pat
from .categories import CATEGORIES, STATUS_IGNORED, STATUS_INCLUDED, STATUS_SUGGESTED
from .classifier import Classification, EntityInfo, classify
from .engine import ARRIVING, AWAY, HOME, Decision, Settings, Signal, decide, parse_time
from .ha_client import HAClient, HAError
from .learning import Learner, is_unreliable, trust_score
from .store import Store

LOG = logging.getLogger(__name__)
STATE_LABEL = {"home": "Home", "asleep": "Asleep", "leaving": "Leaving", "away": "Away", "arriving": "Arriving", "unknown": "Unknown"}


@dataclass
class ScannedEntity:
    info: EntityInfo
    guess: Classification
    status: str
    category: str | None
    role: str | None
    user_set: bool = False
    state: str | None = None

    def to_dict(self) -> dict:
        return {
            "entity_id": self.info.entity_id,
            "name": self.info.name or self.info.entity_id,
            "domain": self.info.domain,
            "area": self.info.area,
            "integration": self.info.integration,
            "device_class": self.info.device_class,
            "disabled": self.info.disabled,
            "available": self.info.available,
            "state": self.state,
            "status": self.status,
            "category": self.category,
            "role": self.role,
            "confidence": round(self.guess.confidence * 100),
            "reasons": self.guess.reasons,
            "user_set": self.user_set,
        }


@dataclass
class Snapshot:
    scanned_at: datetime | None = None
    entities: dict[str, ScannedEntity] = field(default_factory=dict)
    decision: Decision | None = None
    decided_at: datetime | None = None
    error: str | None = None


class BifrostService:
    def __init__(self, client: HAClient, store: Store, options: dict) -> None:
        self.client, self.store, self.options = client, store, options
        self.settings = Settings(
            int(options.get("phone_away_minutes", 10)),
            int(options.get("no_motion_minutes", 15)),
            guest_mode=store.get_value("guest_mode") == "on",
            use_learning=bool(options.get("use_learning", True)),
        )
        self.learner = Learner(store)
        self._last_learn: datetime | None = None
        self.snap = Snapshot()
        self._lock = threading.Lock()
        self._scan_requested = threading.Event()
        self._stop = threading.Event()

    # --- scanning --------------------------------------------------------------
    def scan(self) -> None:
        """Read registries + states and classify every entity."""
        states = {s["entity_id"]: s for s in self.client.get_states()}
        try:
            reg = self.client.registries()
        except HAError as err:
            LOG.warning("Registries not available (%s) – using states only", err)
            reg = {"entities": [], "devices": [], "areas": []}
        areas = {a["area_id"]: a.get("name") for a in reg["areas"]}
        devices = {d["id"]: d for d in reg["devices"]}
        overrides = self.store.get_overrides()
        result: dict[str, ScannedEntity] = {}

        regs = {e["entity_id"]: e for e in reg["entities"]}
        for eid in sorted(set(states) | set(regs)):
            if eid.startswith("sensor.bifrost_") or eid.startswith("binary_sensor.bifrost_"):
                continue  # never classify our own output
            st, re_ = states.get(eid, {}), regs.get(eid, {})
            attrs = st.get("attributes", {})
            dev = devices.get(re_.get("device_id") or "", {})
            area_id = re_.get("area_id") or dev.get("area_id")
            info = EntityInfo(
                entity_id=eid,
                name=attrs.get("friendly_name") or re_.get("name") or re_.get("original_name") or "",
                device_class=attrs.get("device_class") or re_.get("device_class") or re_.get("original_device_class"),
                area=areas.get(area_id) if area_id else None,
                integration=re_.get("platform"),
                unit=attrs.get("unit_of_measurement"),
                manufacturer=dev.get("manufacturer"),
                model=dev.get("model"),
                disabled=bool(re_.get("disabled_by")),
                available=st.get("state") not in (None, "unavailable"),
            )
            guess = classify(info)
            ov = overrides.get(eid)
            if ov:
                ent = ScannedEntity(info, guess, ov["status"], ov["category"] or guess.category, ov["role"] or guess.role, True)
            else:
                ent = ScannedEntity(info, guess, guess.status, guess.category, guess.role)
            ent.state = st.get("state")
            result[eid] = ent
        with self._lock:
            self.snap.entities = result
            self.snap.scanned_at = datetime.now(UTC)
        LOG.info("Scan finished: %d entities, %d used", len(result), sum(1 for e in result.values() if e.status == STATUS_INCLUDED))

    def request_scan(self) -> None:
        self._scan_requested.set()

    # --- deciding ----------------------------------------------------------------
    def evaluate(self) -> Decision:
        now = datetime.now(UTC)
        states = {s["entity_id"]: s for s in self.client.get_states()}
        signals: list[Signal] = []
        with self._lock:
            ents = list(self.snap.entities.values())
        for e in ents:
            st = states.get(e.info.entity_id)
            e.state = st.get("state") if st else None
            if e.status != STATUS_INCLUDED or not e.category or not e.role:
                continue
            if not st or not isinstance(st.get("state"), str):
                # Entity vanished or returned garbage: treat as unavailable so data health drops (fail closed)
                signals.append(Signal(e.info.entity_id, e.info.name or e.info.entity_id, e.category, e.role, "unavailable", now))
                continue
            signals.append(Signal(e.info.entity_id, e.info.name or e.info.entity_id, e.category, e.role, st["state"][:255], parse_time(st.get("last_changed"), now)))
        trust = self.store.get_trust()
        unreliable = {eid for eid, c in trust.items() if is_unreliable(c)}
        d = decide(signals, self.settings, now, unreliable)
        try:
            self._add_context(d, states, now)
        except Exception:  # noqa: BLE001 – context is optional
            LOG.exception("Pattern/calendar context failed")
        try:
            self.learner.observe(signals, d, now)
        except Exception:  # noqa: BLE001 – learning must never stop detection
            LOG.exception("Learning step failed")
        with self._lock:
            changed = not self.snap.decision or self.snap.decision.state != d.state
            self.snap.decision, self.snap.decided_at, self.snap.error = d, now, None
        if changed or now.minute % 15 == 0:
            self.store.add_decision(now, d.state, d.confidence, d.reasons)
        if self.options.get("publish_entities", True):
            self.publish(d)
            self.publish_extra(d, signals, now)
            self.publish_patterns()
        return d

    def publish(self, d: Decision) -> None:
        """Expose Bifrost's result as Home Assistant entities."""
        common = {"attribution": "Bifrost (shadow mode)" if self.options.get("shadow_mode", True) else "Bifrost"}
        try:
            self.client.set_state(
                "sensor.bifrost_home_status",
                d.state,
                {
                    **common,
                    "friendly_name": "Bifrost home status",
                    "icon": "mdi:home-account",
                    "label": STATE_LABEL.get(d.state, d.state),
                    "confidence": d.confidence,
                    "reasons": d.reasons,
                    "people_home": d.people_home,
                    "data_health": d.data_health,
                },
            )
            self.client.set_state(
                "binary_sensor.bifrost_house_empty",
                "on" if d.house_empty else "off",
                {
                    **common,
                    "friendly_name": "Bifrost house empty",
                    "device_class": "occupancy",
                    "icon": "mdi:home-export-outline",
                },
            )
            self.client.set_state(
                "sensor.bifrost_confidence",
                str(d.confidence),
                {
                    **common,
                    "friendly_name": "Bifrost confidence",
                    "unit_of_measurement": "%",
                    "state_class": "measurement",
                    "icon": "mdi:gauge",
                },
            )
            self.client.set_state(
                "sensor.bifrost_reason",
                (d.reasons[0] if d.reasons else "")[:250],
                {
                    **common,
                    "friendly_name": "Bifrost reason",
                    "all_reasons": d.reasons,
                    "icon": "mdi:comment-text-outline",
                },
            )
            self.client.set_state(
                "sensor.bifrost_data_health",
                str(d.data_health),
                {
                    **common,
                    "friendly_name": "Bifrost data health",
                    "unit_of_measurement": "%",
                    "state_class": "measurement",
                    "icon": "mdi:heart-pulse",
                },
            )
        except HAError as err:
            LOG.warning("Publishing entities failed: %s", err)

    def expected_return(self, now: datetime) -> datetime | None:
        """Typical return time on this weekday, learned from the last 8 weeks of decisions."""
        hist = self.store.decisions_since(now - timedelta(days=56))
        times: list[int] = []
        prev = None
        for h in hist:
            if prev == AWAY and h["state"] in (HOME, ARRIVING):
                t = parse_time(h["ts"], now)
                if t.weekday() == now.weekday():
                    times.append(t.hour * 60 + t.minute)
            prev = h["state"]
        later = [m for m in times if m > now.hour * 60 + now.minute]
        if len(times) < 2 or not later:
            return None
        m = int(statistics.median(later))
        return now.replace(hour=m // 60, minute=m % 60, second=0, microsecond=0)

    def publish_extra(self, d: Decision, signals: list[Signal], now: datetime) -> None:
        """v0.2 entities: expected return, anomaly, guest mode, one sensor per person."""
        common = {"attribution": "Bifrost"}
        try:
            ret = self.expected_return(now) if d.state == AWAY else None
            self.client.set_state(
                "sensor.bifrost_expected_return",
                ret.isoformat() if ret else "unknown",
                {
                    **common,
                    "friendly_name": "Bifrost expected return",
                    "device_class": "timestamp",
                    "icon": "mdi:home-clock",
                },
            )
            self.client.set_state(
                "binary_sensor.bifrost_anomaly",
                "on" if d.anomaly else "off",
                {
                    **common,
                    "friendly_name": "Bifrost anomaly",
                    "icon": "mdi:alert-decagram",
                    "description": "Activity while every tracked phone is away – a guest, a person without phone, or something unusual",
                },
            )
            self.client.set_state(
                "binary_sensor.bifrost_guest_mode",
                "on" if self.settings.guest_mode else "off",
                {
                    **common,
                    "friendly_name": "Bifrost guest mode",
                    "icon": "mdi:account-multiple",
                },
            )
            for s in signals:
                if s.entity_id.startswith("person.") and s.available:
                    obj = re.sub(r"[^a-z0-9_]", "_", s.entity_id.split(".", 1)[1])[:60]
                    self.client.set_state(
                        f"sensor.bifrost_person_{obj}",
                        "home" if s.active else "away",
                        {
                            **common,
                            "friendly_name": f"Bifrost {s.name}",
                            "icon": "mdi:account",
                            "since": s.last_changed.isoformat(),
                        },
                    )
        except HAError as err:
            LOG.warning("Publishing extra entities failed: %s", err)

    # --- v0.3 patterns and calendars --------------------------------------------
    def _names(self) -> dict[str, str]:
        with self._lock:
            return {e.info.entity_id: e.info.name or e.info.entity_id for e in self.snap.entities.values()}

    def learn_job(self, now: datetime) -> None:
        """Mine patterns and learn calendars (every few hours). Never raises."""
        self._last_learn = now
        try:
            events = self.store.events_since(now - timedelta(days=56), limit=200000)
            decisions = self.store.decisions_since(now - timedelta(days=56))
            found = pat.mine(events, decisions, lambda v: parse_time(v, now), self._names())
            known = self.store.get_patterns()
            seen_ids = set()
            for p in found:
                seen_ids.add(p.id)
                old = known.get(p.id)
                status = old["status"] if old else "suggested"
                baseline = old["baseline"] if old else None
                if status == "enabled" and baseline is not None and p.precision < baseline - 0.10:
                    status = "changed"  # drift: the pattern no longer holds as well as when it was switched on
                self.store.upsert_pattern(p.id, p.to_dict(), status, baseline, now.isoformat())
            for pid, old in known.items():
                if pid not in seen_ids and old["status"] == "enabled":
                    self.store.upsert_pattern(pid, old["data"], "changed", old["baseline"], old["seen"])
            LOG.info("Pattern mining: %d patterns", len(found))
        except Exception:  # noqa: BLE001
            LOG.exception("Pattern mining failed")
        if not self.options.get("learn_calendars", True):
            return
        try:
            start, end = cal.window(now)
            decisions = self.store.decisions_since(start)
            with self._lock:
                cals = [e.info.entity_id for e in self.snap.entities.values() if e.info.domain == "calendar" and e.status == STATUS_INCLUDED]
            for cid in cals:
                entries = self.client.get_calendar(cid, start.isoformat(), end.isoformat())
                self.store.set_calendar_stats(cid, cal.learn(cid, entries, decisions, lambda v: parse_time(v, now)))
        except Exception:  # noqa: BLE001
            LOG.exception("Calendar learning failed")

    def set_pattern(self, pid: str, status: str) -> dict:
        known = self.store.get_patterns()
        if pid not in known:
            raise KeyError(pid)
        p = known[pid]
        baseline = p["data"]["precision"] / 100 if status == "enabled" else p["baseline"]
        self.store.upsert_pattern(pid, p["data"], status, baseline, p["seen"])
        return {"id": pid, "status": status}

    def _add_context(self, d: Decision, states: dict, now: datetime) -> None:
        """Add pattern progress and calendar hints to the reasons (context only – never changes the state)."""
        recent = [(parse_time(e["ts"], now), tok) for e in self.store.events_since(now - pat.WINDOW) if (tok := pat.step_token(e["entity_id"], e["state"]))]
        self._pattern_live = {}
        for pid, p in self.store.get_patterns().items():
            if p["status"] != "enabled":
                continue
            toks = [f"{s['entity_id']}:{s['state']}" for s in p["data"]["steps"]]
            k = pat.progress(toks, recent, now)
            self._pattern_live[pid] = k
            if k == len(toks):
                d.reasons.append(f"Pattern matched: {p['data']['outcome_label']} usually follows in ~{p['data']['lead']} min")
        if self.options.get("learn_calendars", True):
            active = [(eid, st.get("attributes", {}).get("message", "")) for eid, st in states.items() if eid.startswith("calendar.") and st.get("state") == "on"]
            d.reasons.extend(cal.active_hint(active, self.store.get_calendar_stats()))

    def publish_patterns(self) -> None:
        live = getattr(self, "_pattern_live", {})
        for pid, p in self.store.get_patterns().items():
            if p["status"] != "enabled":
                continue
            n, k = len(p["data"]["steps"]), live.get(pid, 0)
            try:
                self.client.set_state(
                    f"binary_sensor.bifrost_pattern_{pid}",
                    "on" if k == n else "off",
                    {
                        "friendly_name": f"Bifrost pattern: {p['data']['outcome_label']} ({n} steps)",
                        "icon": "mdi:timeline-check",
                        "progress": f"{k}/{n}",
                        "outcome": p["data"]["outcome"],
                        "precision": p["data"]["precision"],
                        "attribution": "Bifrost",
                    },
                )
            except HAError as err:
                LOG.warning("Publishing pattern failed: %s", err)

    def patterns_view(self) -> dict:
        live = getattr(self, "_pattern_live", {})
        out = []
        for pid, p in self.store.get_patterns().items():
            out.append({**p["data"], "status": p["status"], "seen": p["seen"], "baseline": round(100 * p["baseline"]) if p["baseline"] else None, "progress": live.get(pid, 0)})
        order = {"changed": 0, "suggested": 1, "enabled": 2, "disabled": 3}
        out.sort(key=lambda x: (order.get(x["status"], 9), -x["precision"]))
        return {"patterns": out, "last_learn": self._last_learn.isoformat() if self._last_learn else None, "min_support": pat.MIN_SUPPORT, "min_precision": round(100 * pat.MIN_PRECISION)}

    def calendars_view(self) -> dict:
        names = self._names()
        out = []
        for cid, st in self.store.get_calendar_stats().items():
            out.append({"calendar": cid, "name": names.get(cid, cid), "entries": st.get("entries", 0), "away": st.get("away", 0), "insights": cal.insights(st), "updated": st.get("updated")})
        with self._lock:
            used = [e.info.entity_id for e in self.snap.entities.values() if e.info.domain == "calendar" and e.status == STATUS_INCLUDED]
        return {"calendars": out, "used": used, "enabled": bool(self.options.get("learn_calendars", True)), "min_obs": cal.MIN_OBS}

    def set_guest_mode(self, on: bool) -> dict:
        self.store.set_value("guest_mode", "on" if on else "off")
        self.settings.guest_mode = on
        return {"guest_mode": on}

    def accept_suggestions(self, category: str) -> dict:
        """Switch on every suggested entity of one category."""
        with self._lock:
            ids = [e.info.entity_id for e in self.snap.entities.values() if e.status == STATUS_SUGGESTED and e.category == category]
        for eid in ids:
            self.update_entity(eid, STATUS_INCLUDED, None, None)
        return {"accepted": len(ids)}

    def timeline_view(self, hours: int = 24) -> dict:
        now = datetime.now(UTC)
        since = now - timedelta(hours=hours)
        events = self.store.events_since(since)
        changes = []
        prev = None
        for h in self.store.decisions_since(since):
            if h["state"] != prev:
                changes.append({"ts": h["ts"], "state": h["state"], "confidence": h["confidence"]})
            prev = h["state"]
        return {"since": since.isoformat(), "events": events, "decisions": changes, "categories": CATEGORIES}

    def dashboard_view(self, days: int = 14) -> dict:
        now = datetime.now(UTC)
        start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
        hist = self.store.decisions_since(start - timedelta(days=1))
        per_day: dict[str, dict] = {}
        for i in range(days):
            day = (start + timedelta(days=i)).date().isoformat()
            per_day[day] = {"day": day, "minutes": {}, "conf_sum": 0.0, "conf_n": 0, "short_away": 0}
        # minutes per state, by walking the decision timeline
        for i, h in enumerate(hist):
            t0 = max(parse_time(h["ts"], now), start)
            t1 = parse_time(hist[i + 1]["ts"], now) if i + 1 < len(hist) else now
            while t0 < t1:
                day_end = (t0 + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                seg_end = min(t1, day_end)
                key = t0.date().isoformat()
                if key in per_day:
                    mins = (seg_end - t0).total_seconds() / 60
                    m = per_day[key]["minutes"]
                    m[h["state"]] = m.get(h["state"], 0) + mins
                    per_day[key]["conf_sum"] += h["confidence"] * mins
                    per_day[key]["conf_n"] += mins
                t0 = seg_end
            # an "Away" that ends within 15 minutes is a likely wrong decision
            if h["state"] == AWAY and i + 1 < len(hist) and hist[i + 1]["state"] != AWAY:
                if (parse_time(hist[i + 1]["ts"], now) - parse_time(h["ts"], now)) < timedelta(minutes=15):
                    key = parse_time(h["ts"], now).date().isoformat()
                    if key in per_day:
                        per_day[key]["short_away"] += 1
        out = []
        for v in per_day.values():
            total = sum(v["minutes"].values()) or 0
            unknown = v["minutes"].get("unknown", 0)
            out.append(
                {
                    "day": v["day"],
                    "minutes": {k: round(x) for k, x in v["minutes"].items()},
                    "avg_confidence": round(v["conf_sum"] / v["conf_n"]) if v["conf_n"] else None,
                    "decided_share": round(100 * (total - unknown) / total) if total else None,
                    "short_away": v["short_away"],
                }
            )
        trust = self.store.get_trust()
        with self._lock:
            names = {e.info.entity_id: (e.info.name or e.info.entity_id, e.category) for e in self.snap.entities.values()}
        sensors = sorted(
            (
                {
                    "entity_id": k,
                    "name": names.get(k, (k, None))[0],
                    "category": names.get(k, (k, None))[1],
                    "agree": a,
                    "disagree": dis,
                    "score": round(100 * trust_score(a, dis)),
                    "unreliable": is_unreliable((a, dis)),
                }
                for k, (a, dis) in trust.items()
            ),
            key=lambda x: x["score"],
        )
        return {"days": out, "sensors": sensors, "use_learning": self.settings.use_learning}

    # --- user changes ----------------------------------------------------------
    def update_entity(self, entity_id: str, status: str, category: str | None, role: str | None) -> dict:
        with self._lock:
            e = self.snap.entities.get(entity_id)
            if not e:
                raise KeyError(entity_id)
        self.store.set_override(entity_id, status, category, role)
        with self._lock:
            e.status, e.user_set = status, True
            e.category, e.role = category or e.guess.category, role or e.guess.role
            return e.to_dict()

    # --- views for the web UI ------------------------------------------------------
    def status_view(self) -> dict:
        with self._lock:
            d, at, err = self.snap.decision, self.snap.decided_at, self.snap.error
        return {
            "version": __version__,
            "shadow_mode": bool(self.options.get("shadow_mode", True)),
            "decided_at": at.isoformat() if at else None,
            "error": err,
            "decision": None if not d else {**asdict(d), "label": STATE_LABEL.get(d.state, d.state), "last_activity": d.last_activity.isoformat() if d.last_activity else None},
            "history": self.store.history(24),
            "guest_mode": self.settings.guest_mode,
        }

    def entities_view(self) -> dict:
        with self._lock:
            ents = [e.to_dict() for e in self.snap.entities.values()]
            at = self.snap.scanned_at
        status = Counter(e["status"] for e in ents)
        by_domain: dict[str, list[int]] = {}
        for e in ents:
            v = by_domain.setdefault(e["domain"], [0, 0])
            v[0] += 1
            v[1] += e["status"] == STATUS_INCLUDED
        by_cat = Counter(e["category"] for e in ents if e["status"] == STATUS_INCLUDED and e["category"])
        return {
            "scanned_at": at.isoformat() if at else None,
            "summary": {
                "total": len(ents),
                "relevant": sum(1 for e in ents if e["status"] != STATUS_IGNORED),
                "by_status": dict(status),
                "disabled_in_ha": sum(1 for e in ents if e["disabled"] and e["status"] != STATUS_IGNORED),
                "unavailable": sum(1 for e in ents if not e["available"] and not e["disabled"] and e["status"] != STATUS_IGNORED),
                "by_domain": dict(sorted(by_domain.items(), key=lambda x: -x[1][0])),
                "by_category": {k: by_cat.get(k, 0) for k in CATEGORIES},
            },
            "categories": CATEGORIES,
            "entities": ents,
        }

    # --- loop --------------------------------------------------------------------
    def run_forever(self) -> None:
        interval = int(self.options.get("update_interval", 30))
        last_scan_day = None
        while not self._stop.is_set():
            try:
                today = datetime.now(UTC).date()
                if self._scan_requested.is_set() or not self.snap.entities or last_scan_day != today:
                    self._scan_requested.clear()
                    self.scan()
                    last_scan_day = today
                    self.store.prune()
                self.evaluate()
                now = datetime.now(UTC)
                if self._last_learn is None or now - self._last_learn > timedelta(hours=6):
                    self.learn_job(now)
            except HAError as err:
                LOG.error("Home Assistant not reachable: %s", err)
                with self._lock:
                    self.snap.error = str(err)
            except Exception:  # noqa: BLE001 – keep the loop alive, log the details
                LOG.exception("Unexpected error in main loop")
            self._scan_requested.wait(timeout=interval)

    def stop(self) -> None:
        self._stop.set()
        self._scan_requested.set()
