"""Core loop: scan Home Assistant, classify entities, decide, publish."""

from __future__ import annotations

import logging
import threading
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from . import __version__
from .categories import CATEGORIES, STATUS_IGNORED, STATUS_INCLUDED
from .classifier import Classification, EntityInfo, classify
from .engine import Decision, Settings, Signal, decide, parse_time
from .ha_client import HAClient, HAError
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
        self.settings = Settings(int(options.get("phone_away_minutes", 10)), int(options.get("no_motion_minutes", 15)))
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
        d = decide(signals, self.settings, now)
        with self._lock:
            changed = not self.snap.decision or self.snap.decision.state != d.state
            self.snap.decision, self.snap.decided_at, self.snap.error = d, now, None
        if changed or now.minute % 15 == 0:
            self.store.add_decision(now, d.state, d.confidence, d.reasons)
        if self.options.get("publish_entities", True):
            self.publish(d)
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
