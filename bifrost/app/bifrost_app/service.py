"""Core loop: scan Home Assistant, classify entities, decide, publish."""

from __future__ import annotations

import json
import logging
import re
import statistics
import threading
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta

from . import __version__, i18n
from . import calendars as cal
from . import patterns as pat
from .balance import signal as _signal
from .brain import Brain
from .categories import CATEGORIES, STATUS_IGNORED, STATUS_INCLUDED
from .classifier import Classification, EntityInfo, classify
from .engine import ARRIVING, AWAY, HOME, Decision, Settings, Signal, decide, parse_time
from .ha_client import HAClient, HAError
from .learning import Learner, is_unreliable, trust_score
from .live import AUTOMATION, SCHEDULED, LiveBoard, NumericEvents, OriginLearner, classify_origin
from .optimize import suggestions as opt_suggestions
from .people import public as person_public
from .preprocess import DuplicateDetector, Edge, EdgeFilter
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
            "disabled_by": self.info.disabled_by,
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


def _is_number(v: str | None) -> bool:
    try:
        float(v or "x")
    except ValueError:
        return False
    return True


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
        self.language = self._initial_language()
        self.live = LiveBoard()
        self.numeric = NumericEvents()
        self.origins = OriginLearner()
        try:
            self.origins.load(json.loads(store.get_value("origins") or "{}"))
        except ValueError:
            LOG.warning("Stored origin data unreadable – starting fresh")
        self.floors: dict[str, dict] = {}
        self._states: dict[str, dict] = {}
        self.snap = Snapshot()
        self._lock = threading.Lock()
        self._scan_requested = threading.Event()
        self._stop = threading.Event()
        # 0.4 live event stream
        self.edges = EdgeFilter()
        self.duplicates = DuplicateDetector()
        self.stream = {"connected": False, "events": 0, "since": None, "error": None}
        self._stream_lock = threading.Lock()
        self.brain = Brain(store, options)
        self.extra: dict = {}

    # --- scanning --------------------------------------------------------------
    def scan(self) -> None:
        """Read registries + states and classify every entity."""
        states = {s["entity_id"]: s for s in self.client.get_states()}
        try:
            reg = self.client.registries()
        except HAError as err:
            LOG.warning("Registries not available (%s) – using states only", err)
            reg = {"entities": [], "devices": [], "areas": [], "floors": []}
        areas = {a["area_id"]: a.get("name") for a in reg["areas"]}
        floors = {f["floor_id"]: f for f in reg.get("floors") or [] if f.get("floor_id")}
        area_floor: dict[str, dict] = {}
        for a in reg["areas"]:
            f = floors.get(a.get("floor_id") or "")
            if a.get("name"):
                area_floor[a["name"]] = {"floor": f.get("name") if f else None, "level": f.get("level") if f else None, "icon": a.get("icon")}
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
                disabled_by=re_.get("disabled_by"),
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
        # ≤ 0.4.2: access entities were chosen in the People tab → now role Identity in Setup
        legacy = self.brain.people.access_entities()
        for eid in legacy:
            e = result.get(eid)
            if e is not None and not e.user_set:
                self.store.set_override(eid, STATUS_INCLUDED, "security", "Identity")
                e.status, e.category, e.role, e.user_set = STATUS_INCLUDED, "security", "Identity", True
        if legacy:
            self.store.set_value("access_entities", "[]")
        with self._lock:
            self.snap.entities = result
            self.snap.scanned_at = datetime.now(UTC)
            self.floors = area_floor
        self.brain.set_meta(
            {
                eid: {"name": e.info.name, "category": e.category, "device_class": e.info.device_class, "area": e.info.area, "integration": e.info.integration, "role": e.role}
                for eid, e in result.items()
                if e.status == STATUS_INCLUDED
            }
        )
        LOG.info("Scan finished: %d entities, %d used", len(result), sum(1 for e in result.values() if e.status == STATUS_INCLUDED))

    def request_scan(self) -> None:
        self._scan_requested.set()

    # --- deciding ----------------------------------------------------------------
    def evaluate(self) -> Decision:
        now = datetime.now(UTC)
        states = {s["entity_id"]: s for s in self.client.get_states()}
        self._states = states
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
        automated = self.live.automated(timedelta(hours=24), now)
        d = decide(signals, self.settings, now, unreliable, automated)
        try:
            self._add_context(d, states, now)
        except Exception:  # noqa: BLE001 – context is optional
            LOG.exception("Pattern/calendar context failed")
        try:
            d, self.extra = self.brain.tick(d, states, now, self.settings.guest_mode)
        except Exception:  # noqa: BLE001 – fall back to the plain rule decision
            LOG.exception("Guard/recognition step failed")
            self.extra = {}
        if not self.store.get_value("first_decision"):
            self.store.set_value("first_decision", now.isoformat())
        try:
            self.learner.observe(signals, d, now, record_events=not self.stream["connected"])
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
                    "reasons": [self.tr(r) for r in d.reasons],
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
                self.tr(d.reasons[0] if d.reasons else "")[:250],
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
            ex = self.extra or {}
            sus = ex.get("suspicion")
            self.client.set_state(
                "binary_sensor.bifrost_suspicious_entry",
                "on" if sus and int(self.options.get("suspicious_entry_level", 2)) >= 2 else "off",
                {**common, "friendly_name": "Bifrost suspicious entry", "device_class": "safety", "icon": "mdi:shield-alert", "door": (sus or {}).get("door")},
            )
            q = ex.get("questions") or {}
            self.client.set_state(
                "sensor.bifrost_open_questions",
                str(q.get("question", 0) + q.get("suggestion", 0)),
                {**common, "friendly_name": "Bifrost open questions", "icon": "mdi:help-circle-outline", "questions": q.get("question", 0), "suggestions": q.get("suggestion", 0)},
            )
            self.client.set_state(
                "sensor.bifrost_unknown_people",
                str(ex.get("unknown_min", 0)),
                {**common, "friendly_name": "Bifrost unknown people (at least)", "icon": "mdi:account-question"},
            )
            for row in (ex.get("ledger") or {}).get("people", []):
                if self.options.get("person_entities", True):
                    self.client.set_state(
                        f"sensor.bifrost_person_{row['id']}",
                        row["state"],
                        {**common, "friendly_name": f"Bifrost {row['name']}", "icon": "mdi:account", "reason": row["reason"], "strength": row.get("strength")},
                    )
            bal = self.brain.balance_view(now, d.data_health, self._departures(now))
            guard_ok = all(c["ok"] for c in ex.get("checks", []))
            self.client.set_state(
                "binary_sensor.bifrost_empty_confirmed",
                "on" if _signal(bal["signal_option"], bal["gate"]["passed"], d.state, d.confidence, guard_ok) else "off",
                {**common, "friendly_name": "Bifrost house empty confirmed", "icon": "mdi:shield-home", "gate_passed": bal["gate"]["passed"], "option": bal["signal_option"]},
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
        cal_entries: dict[str, list[dict]] = {}
        if self.options.get("learn_calendars", True):
            try:
                start, end = cal.window(now, days=56)
                with self._lock:
                    cids = [e.info.entity_id for e in self.snap.entities.values() if e.info.domain == "calendar" and e.status == STATUS_INCLUDED]
                for cid in cids:
                    cal_entries[cid] = self.client.get_calendar(cid, start.isoformat(), end.isoformat())
            except Exception:  # noqa: BLE001
                LOG.exception("Reading calendars failed")
        try:
            with self._lock:
                current = {k: e.state for k, e in self.snap.entities.items()}
            res = self.brain.learn(now, cal_entries, self.duplicates.candidates(), current)
            LOG.info("Recognition learned: %s", res)
        except Exception:  # noqa: BLE001
            LOG.exception("Recognition learning failed")
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

    def _initial_language(self) -> str:
        """Stored choice, otherwise the Home Assistant language on first start."""
        stored = self.store.get_value("language")
        if stored in i18n.LANGUAGES:
            return stored
        try:
            cfg = self.client.get_config()
            lang = i18n.normalize(cfg.get("language") if isinstance(cfg, dict) else None)
        except Exception as err:  # noqa: BLE001
            LOG.info("Home Assistant language not available (%s) – using English", err)
            lang = "en"
        self.store.set_value("language", lang)
        return lang

    def set_language(self, lang: str) -> dict:
        if lang not in i18n.LANGUAGES:
            raise ValueError("language must be de or en")
        self.store.set_value("language", lang)
        self.language = lang
        return {"language": lang}

    def i18n_view(self) -> dict:
        return {"language": self.language, "de": i18n.DE}

    def tr(self, text: str) -> str:
        return i18n.tr(text, self.language)

    def set_guest_mode(self, on: bool) -> dict:
        self.store.set_value("guest_mode", "on" if on else "off")
        self.settings.guest_mode = on
        return {"guest_mode": on}

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
            "language": self.language,
            "shadow_mode": bool(self.options.get("shadow_mode", True)),
            "decided_at": at.isoformat() if at else None,
            "error": err,
            "decision": None if not d else {**asdict(d), "label": STATE_LABEL.get(d.state, d.state), "last_activity": d.last_activity.isoformat() if d.last_activity else None},
            "history": self.store.history(24),
            "guest_mode": self.settings.guest_mode,
            "stream": self.stream_view(),
            "guard": {k: (self.extra or {}).get(k) for k in ("checks", "suspicion", "unknown_min", "people_inside_min", "in_progress", "learning", "questions")},
            "ledger": (self.extra or {}).get("ledger"),
            "capability": self.brain.detector.model.get("capability", {}),
        }

    def optimizations_view(self) -> dict:
        """Where category or role of a signal differs from what works best – one suggestion per entity."""
        with self._lock:
            ents = [{**e.to_dict(), "guess_category": e.guess.category, "guess_role": e.guess.role} for e in self.snap.entities.values()]
        model = self.brain.detector.model or {}
        try:
            dismissed = set(json.loads(self.store.get_value("opt_dismissed") or "[]"))
        except ValueError:
            dismissed = set()
        items = opt_suggestions(ents, model.get("roles", {}), model.get("doctor", []), dismissed)
        return {"items": items, "dismissed": len(dismissed)}

    def dismiss_optimization(self, entity_id: str, key: str) -> dict:
        try:
            cur = set(json.loads(self.store.get_value("opt_dismissed") or "[]"))
        except ValueError:
            cur = set()
        cur.add(f"{entity_id}|{key}")
        self.store.set_value("opt_dismissed", json.dumps(sorted(cur)[-500:]))
        return {"dismissed": len(cur)}

    def reset_optimizations(self) -> dict:
        self.store.set_value("opt_dismissed", "[]")
        return {"dismissed": 0}

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

    # --- 0.4–1.0 views and actions --------------------------------------------------
    def _departures(self, now: datetime) -> int:
        dec = self.store.decisions_since(now - timedelta(days=60))
        return sum(1 for g, _ in pat.outcomes_from_decisions(dec, lambda v: parse_time(v, now)) if g == "departure")

    def people_view(self) -> dict:
        led = (self.extra or {}).get("ledger") or {}
        rows = {r["id"]: r for r in led.get("people", [])}
        names = self._names()
        irks = self.brain.people.irks()
        stats = self.store.get_obj("stats", "access_users") or {}
        out = []
        for p in self.brain.people.all():
            out.append({
                **person_public(p), "now": rows.get(p.id),
                "tracker_names": [names.get(e, e) for e in p.trackers + p.tags],
                "calendar_names": [names.get(e, e) for e in p.calendars],
                "irks": [k["label"] for k in irks if k.get("owner") == p.id],
                "unlocks": stats.get(p.id, 0),
            })  # fmt: skip
        return {
            "people": out,
            "unknown_min": led.get("unknown_min", 0),
            "household_calendars": [names.get(e, e) for e in self.brain.people.household_calendars()],
            "shared_access": self.brain.people.shared_access(),
            "timing": {k: v for k, v in self.brain.timing.items() if not k.startswith("_")},
        }

    def sources_view(self) -> dict:
        """Everything Setup needs to assign sources: owners, identity entities with reported values, IRK keys."""
        ids = self._identity_ids()
        since = datetime.now(UTC) - timedelta(days=60)
        amap = self.brain.people.access_map()
        names = self._names()
        return {
            "people": [{"id": p.id, "name": p.name} for p in self.brain.people.all()],
            "owners": self.brain.people.owners(),
            "identity": [{"entity_id": e, "name": names.get(e, e), "seen": [{"value": v, "target": amap.get(v, "")} for v in self.store.distinct_states([e], since, kind="access_raw")]} for e in ids],
            "irks": self.brain.people.irks(),
        }

    def save_person(self, body: dict) -> dict:
        p = self.brain.people.save(body)
        return person_public(p)

    def set_owner(self, entity_id: object, owner: object) -> dict:
        """Assign a source to a person (or the household) – assigning means using it, so it is switched on."""
        res = self.brain.people.set_owner(entity_id, owner)
        if owner:
            with self._lock:
                e = self.snap.entities.get(entity_id)
            if e is not None and e.status != STATUS_INCLUDED:
                self.update_entity(entity_id, STATUS_INCLUDED, e.category or e.guess.category, e.role or e.guess.role)
                res["switched_on"] = True
        return res

    def delete_person(self, pid: str) -> dict:
        return {"deleted": self.brain.people.delete(pid)}

    def house_view(self) -> dict:
        return {**self.brain.house_view(self._names()), "people_inside_min": (self.extra or {}).get("people_inside_min", 0)}

    def live_view(self) -> dict:
        """The house right now: floors and areas from Home Assistant, every used signal with its last change."""
        now = datetime.now(UTC)
        names = self._names()
        house = self.brain.house_view(names)
        trust = self.store.get_trust()
        unreliable = {eid for eid, c in trust.items() if is_unreliable(c)}
        with self._lock:
            ents = {k: e for k, e in self.snap.entities.items() if e.status == STATUS_INCLUDED}
            floors_of = dict(self.floors)
        with self._stream_lock:
            last = dict(self.live.last)
            path = self.live.last_path(now)
        walk = [x for x in house["map"].get("links", []) if x.get("kind") == "walk"]
        neigh: dict[str, list[dict]] = {}
        for x in walk:
            neigh.setdefault(x["a"], []).append({"entity_id": x["b"], "typical": x.get("typical"), "count": x.get("count")})
            neigh.setdefault(x["b"], []).append({"entity_id": x["a"], "typical": x.get("typical"), "count": x.get("count")})
        sides = house.get("sides", {})
        areas: dict[str | None, list[dict]] = {}
        for eid, e in ents.items():
            if e.category in ("calendar", "devices") or eid.startswith(("calendar.", "person.", "device_tracker.", "zone.", "weather.")):
                continue  # not in a room: shown under People
            lv = last.get(eid)
            st = self._states.get(eid) or {}
            ts = lv.ts if lv else parse_time(st.get("last_changed"), now) if st.get("last_changed") else None
            noise = e.role == "Noise" or eid in unreliable
            sig = {
                "entity_id": eid, "name": e.info.name or eid, "category": e.category, "role": e.role,
                "icon": (CATEGORIES.get(e.category or "") or {}).get("icon", ""),
                "state": (lv.state if lv else st.get("state") or e.state or "")[:64],
                "ts": ts.isoformat() if ts else None, "origin": lv.origin if lv else None, "event": lv.event if lv else "",
                "trend": self.numeric.trend(eid), "noise": noise,
                "side": (sides.get(eid) or {}).get("side"),
                "neighbours": sorted(neigh.get(eid, []), key=lambda n: -(n.get("count") or 0))[:3],
            }  # fmt: skip
            sig["active"] = bool(ts and (now - ts).total_seconds() < 60 and not noise and sig["origin"] not in (AUTOMATION, SCHEDULED))
            areas.setdefault(e.info.area, []).append(sig)
        floors: dict[str | None, dict] = {}
        for area, sigs in areas.items():
            if area is None:
                continue
            fl = floors_of.get(area) or {}
            f = floors.setdefault(fl.get("floor"), {"name": fl.get("floor"), "level": fl.get("level"), "areas": []})
            sigs.sort(key=lambda x: x["ts"] or "", reverse=True)
            f["areas"].append({"name": area, "icon": fl.get("icon"), "signals": sigs, "active": any(x["active"] for x in sigs), "last": sigs[0]["ts"] if sigs else None})
        for f in floors.values():
            f["areas"].sort(key=lambda a: (not a["active"], a["name"].lower()))
        empty_areas = sorted(a for a in floors_of if a not in areas)
        for a in empty_areas:
            fl = floors_of[a]
            floors.setdefault(fl.get("floor"), {"name": fl.get("floor"), "level": fl.get("level"), "areas": []})["areas"].append(
                {"name": a, "icon": fl.get("icon"), "signals": [], "active": False, "last": None}
            )
        floor_list = sorted(floors.values(), key=lambda f: (f["level"] is None, f["level"] if isinstance(f["level"], int) else 0, f["name"] or ""))
        all_sigs = [x for v in areas.values() for x in v]
        latest = max((x for x in all_sigs if x["origin"] and not x["noise"] and x["origin"] not in (AUTOMATION, SCHEDULED)), key=lambda x: x["ts"], default=None)
        area_of = {x["entity_id"]: a for a, v in areas.items() for x in v}
        gaps = [{"kind": "door_no_direction", "entity_id": en["door"]} for en in house.get("entrances", []) if not en.get("direction")]
        gaps += [{"kind": "area_without_signal", "area": a} for a in empty_areas]
        gaps += [{"kind": "signal_without_area", "entity_id": x["entity_id"]} for x in areas.get(None, [])]
        led = (self.extra or {}).get("ledger") or {}
        return {
            **house,
            "now": now.isoformat(),
            "floors": floor_list,
            "unassigned": areas.get(None, []),
            "gaps": gaps,
            "people": [{"name": r.get("name"), "state": r.get("state")} for r in led.get("people", [])],
            "unknown_min": led.get("unknown_min", 0),
            "kpis": {
                "people_home": sum(1 for r in led.get("people", []) if r.get("state") == "home"),
                "active_areas": sum(1 for f in floor_list for a in f["areas"] if a["active"]),
                "last": {"entity_id": latest["entity_id"], "area": area_of.get(latest["entity_id"]), "ts": latest["ts"]} if latest else None,
                "health": self.snap.decision.data_health if self.snap.decision else None,
            },
            "last_path": [{**p, "ts": p["ts"].isoformat(), "area": area_of.get(p["entity_id"]), "category": (ents.get(p["entity_id"]) and ents[p["entity_id"]].category) or ""} for p in path],
            "in_progress": (self.extra or {}).get("in_progress", []),
            "links": [{**x, "a_area": area_of.get(x["a"]), "b_area": area_of.get(x["b"])} for x in walk],
            "names": names,
            "people_inside_min": (self.extra or {}).get("people_inside_min", 0),
        }

    def recognition_view(self) -> dict:
        return {**self.brain.recognition_view(self._names()), "in_progress": (self.extra or {}).get("in_progress", []), "names": self._names()}

    def deviations_view(self) -> dict:
        return {"items": self.brain.inbox.deviations(), "names": self._names()}

    def questions_view(self) -> dict:
        return {
            "items": [q for q in self.brain.inbox.all() if q["status"] in ("open", "waiting")][:60],
            "done": [q for q in self.brain.inbox.all() if q["status"] == "answered"][:30],
            "names": self._names(),
        }

    def answer(self, qid: str, answer: str, label: str | None) -> dict:
        return self.brain.answer(qid, answer, label, datetime.now(UTC), self.store.set_override)

    def correct(self, actual: str) -> dict:
        with self._lock:
            said = self.snap.decision.state if self.snap.decision else "unknown"
        return self.brain.correct(said, actual, datetime.now(UTC))

    def balance_view(self) -> dict:
        now = datetime.now(UTC)
        with self._lock:
            health = self.snap.decision.data_health if self.snap.decision else 0
        return self.brain.balance_view(now, health, self._departures(now))

    # --- live event stream (0.4) -------------------------------------------------
    def _included(self) -> dict[str, ScannedEntity]:
        with self._lock:
            return {k: e for k, e in self.snap.entities.items() if e.status == STATUS_INCLUDED}

    def _seed_edges(self) -> None:
        """After (re)connecting: learn the current state of every used signal without creating edges."""
        inc = self._included()
        try:
            states = self.client.get_states()
        except HAError:
            states = []
        now = datetime.now(UTC)
        with self._stream_lock:
            for st in states:
                eid = st.get("entity_id")
                if eid in inc:
                    self.edges.feed(eid, st.get("state"), parse_time(st.get("last_changed"), now))
            self.stream.update(connected=True, since=now.isoformat(), error=None)
        LOG.info("Live event stream connected")

    def _identity_ids(self) -> list[str]:
        """Entities that say who it was: role Identity, plus smart locks (who unlocked is an attribute)."""
        return sorted(k for k, e in self._included().items() if e.role == "Identity" or e.info.domain == "lock")

    def _on_identity(self, ent: ScannedEntity, state: str | None, ts: datetime, attrs: dict | None) -> None:
        eid, domain = ent.info.entity_id, ent.info.domain
        attrs = attrs or {}
        user = next((attrs[k] for k in ("changed_by", "user", "user_name", "username", "code_slot_name", "code_name", "last_user", "user_id", "name") if attrs.get(k)), "")
        if domain == "lock":
            if (state or "").lower() not in ("unlocked", "open", "opening", "unlocking"):
                return  # locking is an ordinary signal; only an unlock says who came in
            reported = user
        elif domain == "event":
            reported = user or ""
        else:
            reported = (state or "").strip()
            if not reported or reported.lower() in ("unknown", "unavailable", "none", "-", "0"):
                return  # value was cleared after the last unlock
        reported = reported[:40]
        target = self.brain.people.access_target(reported) if reported else None
        target = target or "unknown"
        name = ent.info.name or eid
        if reported:
            self.store.add_event(ts, eid, name, ent.category or "", ent.role or "", reported, kind="access_raw")
        self.store.add_event(ts, eid, name, ent.category or "", ent.role or "", target, kind="access")
        with self._stream_lock:
            self.live.note(eid, ts, reported or target, "person", "access_denied" if target == "denied" else "access_ok")
        try:
            self.brain.on_edge({"ts": ts, "entity_id": eid, "kind": "access", "state": target})
        except Exception:  # noqa: BLE001 – recognition must never break the stream
            LOG.exception("Brain could not process an access event")

    def on_state_changed(self, entity_id: str, state: str | None, ts: datetime, origin: str = "device", attrs: dict | None = None) -> None:
        ent = self._included().get(entity_id)
        if ent is None:
            return
        if ent.role == "Identity" or ent.info.domain == "lock":
            self._on_identity(ent, state, ts, attrs)
            if ent.role == "Identity":
                return
        cat = ent.category or ""
        with self._stream_lock:
            edges = self.edges.feed(entity_id, state, ts)
            event = self.numeric.feed(entity_id, state, ts, ent.info.device_class, ent.info.unit)
            for e in edges:
                self.duplicates.feed(e)
                self.stream["events"] += 1
            scheduled = False
            if origin == "device" and any(e.kind == "on" for e in edges) and cat in ("manual", "media", "energy", "modes"):
                scheduled = self.origins.scheduled(entity_id, ts)
                self.origins.record(entity_id, ts)
                self.store.set_value("origins", json.dumps(self.origins.dump()))
            how = classify_origin(origin, cat, scheduled)
            if edges or event:
                self.live.note(entity_id, ts, (state or "")[:64], how, event or "")
        if event:
            edges = [*edges, Edge(ts, entity_id, "event", event)]
        for e in edges:
            kind = "auto" if how in (AUTOMATION, SCHEDULED) and e.kind in ("on", "off") else e.kind
            self.store.add_event(e.ts, entity_id, ent.info.name or entity_id, cat, ent.role or "", e.state, kind=kind)
            if not self.store.get_value("first_edge"):
                self.store.set_value("first_edge", e.ts.isoformat())
            try:
                self.brain.on_edge({"ts": e.ts, "entity_id": entity_id, "kind": kind, "state": e.state})
            except Exception:  # noqa: BLE001 – recognition must never break the stream
                LOG.exception("Brain could not process an edge")

    def _stream_loop(self) -> None:
        backoff = 5
        while not self._stop.is_set():
            try:
                self.client.stream_state_changes(self.on_state_changed, self._stop, on_connected=self._seed_edges)
                backoff = 5
            except Exception as err:  # noqa: BLE001 – reconnect on any connection problem
                with self._stream_lock:
                    self.stream.update(connected=False, error=str(err)[:200])
                LOG.warning("Live event stream lost (%s) – retry in %d s", err, backoff)
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 120)
        with self._stream_lock:
            self.stream["connected"] = False

    def start_stream(self) -> threading.Thread | None:
        if not self.options.get("event_stream", True) or not hasattr(self.client, "stream_state_changes"):
            return None
        t = threading.Thread(target=self._stream_loop, name="bifrost-stream", daemon=True)
        t.start()
        return t

    def stream_view(self) -> dict:
        with self._stream_lock:
            return {**self.stream, "flicker_ignored": self.edges.flicker_count(), "duplicates": self.duplicates.candidates()}

    # --- loop --------------------------------------------------------------------
    def run_forever(self) -> None:
        interval = int(self.options.get("update_interval", 30))
        last_scan_day = None
        stream_started = False
        while not self._stop.is_set():
            try:
                today = datetime.now(UTC).date()
                if self._scan_requested.is_set() or not self.snap.entities or last_scan_day != today:
                    self._scan_requested.clear()
                    self.scan()
                    last_scan_day = today
                    self.store.prune()
                if not stream_started:
                    stream_started = True
                    self.start_stream()
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
