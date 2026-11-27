"""Where Bifrost's own entities go (0.12): MQTT Discovery, with /api/states as the fallback.

Every ``set_state`` of the service lands here. The outlet

* publishes the entity via MQTT Discovery under one device "Bifrost" (unique_id, device class, unit,
  availability with a Last Will, retained values, ``expire_after`` for the safety entities) – or,
  without a broker, writes it with ``POST /api/states`` as before;
* adds ``updated_at`` and ``valid_until`` to every entity, so a consumer can tell a stale value;
* fails closed: on start, on stop, after an error and when the loop hangs, the safety entities
  (``empty_confirmed``, ``house_empty``) are written ``off`` first;
* keeps a registry of all entities with their last value, so the Setup card can list them and the owner can
  switch single entities off (removed from HA, still computed inside Bifrost);
* removes the old /api/states entities once MQTT works, and lists leftovers it could not remove.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from datetime import UTC, datetime, timedelta

LOG = logging.getLogger(__name__)

SAFETY = ("binary_sensor.bifrost_empty_confirmed", "binary_sensor.bifrost_house_empty")
PREFIX = "bifrost"
AVAIL = f"{PREFIX}/status"
OWN_ID = re.compile(r"^(sensor|binary_sensor)\.bifrost_[a-z0-9_]{1,80}$")
KINDS = ("safety", "status", "people", "patterns", "zones", "visitors")
STATUS_IDS = {"home_status", "confidence", "reason", "data_health", "expected_return", "anomaly", "guest_mode", "open_questions", "unknown_people", "suspicious_entry"}


def kind_of(entity_id: str) -> str:
    if entity_id in SAFETY:
        return "safety"
    obj = entity_id.split(".", 1)[1][len(PREFIX) + 1 :]
    if obj in STATUS_IDS or obj.startswith("p_"):
        return "status"
    if obj.startswith("person_"):
        return "people"
    if obj.startswith("zone_"):
        return "zones"
    if obj.startswith("visitor_"):
        return "visitors"
    return "patterns"


def discovery(entity_id: str, attrs: dict, version: str, expire: int | None) -> tuple[str, dict]:
    """(config topic, config payload) for one entity."""
    domain, obj = entity_id.split(".", 1)
    name = str(attrs.get("friendly_name") or obj).strip()
    if name.lower().startswith("bifrost "):
        name = name[8:]
    cfg = {
        "name": name[:1].upper() + name[1:],
        "unique_id": f"{obj}_{domain}",
        "default_entity_id": entity_id,
        "state_topic": f"{PREFIX}/{domain}/{obj}/state",
        "json_attributes_topic": f"{PREFIX}/{domain}/{obj}/attr",
        "availability_topic": AVAIL,
        "device": {"identifiers": ["bifrost"], "name": "Bifrost", "manufacturer": "Bifrost", "model": "Home Assistant app", "sw_version": version},
    }
    if domain == "binary_sensor":
        cfg["payload_on"], cfg["payload_off"] = "on", "off"
    for key in ("device_class", "unit_of_measurement", "icon", "state_class"):
        if attrs.get(key):
            cfg[key] = attrs[key]
    if expire:
        cfg["expire_after"] = expire
    return f"homeassistant/{domain}/{PREFIX}/{obj}/config", cfg


class Outlet:
    def __init__(self, client, store, interval: int = 30, version: str = "") -> None:  # noqa: ANN001
        self.client, self.store, self.version = client, store, version
        self.valid = timedelta(seconds=3 * max(5, interval))
        self.mqtt = None  # MQTTClient when a broker is available
        self.broker: str | None = None
        self._lock = threading.RLock()
        self.entities: dict[str, dict] = {}  # id → {"state", "attrs", "at", "kind"}
        self._announced: set[str] = set()
        try:
            self.off: set[str] = set(json.loads(store.get_value("entities_off") or "[]"))
        except ValueError:
            self.off = set()
        self.failed_safe = False

    # --- MQTT wiring ---------------------------------------------------------------
    def attach_mqtt(self, mqtt_client, broker: str) -> None:  # noqa: ANN001
        self.mqtt, self.broker = mqtt_client, broker
        mqtt_client.on_connect = self._on_connect
        mqtt_client.on_message = self._on_message
        mqtt_client.subscribe("homeassistant/status")

    @property
    def mode(self) -> str:
        return "mqtt" if self.mqtt is not None and self.mqtt.connected else "rest"

    def _on_connect(self) -> None:
        """After every (re)connect: safety off first, then online, then discovery and the current values."""
        m = self.mqtt
        for eid in SAFETY:
            if eid not in self.off:
                m.publish(self._topic(eid, "state"), "off", retain=True)
        m.publish(AVAIL, "online", retain=True)
        with self._lock:
            self._announced.clear()
            items = list(self.entities.items())
        for eid, e in items:
            if eid not in self.off:
                self._publish_mqtt(eid, e["state"], e["attrs"])
        self._migrate()

    def _on_message(self, topic: str, payload: bytes) -> None:
        if topic == "homeassistant/status" and payload.strip() == b"online":
            LOG.info("Home Assistant restarted – sending discovery again")
            self._on_connect()

    def _topic(self, eid: str, what: str) -> str:
        domain, obj = eid.split(".", 1)
        return f"{PREFIX}/{domain}/{obj}/{what}"

    def _publish_mqtt(self, eid: str, state: str, attrs: dict) -> bool:
        m = self.mqtt
        if eid not in self._announced:
            topic, cfg = discovery(eid, attrs, self.version, int(self.valid.total_seconds()) if eid in SAFETY or eid == "sensor.bifrost_home_status" else None)
            if not m.publish(topic, json.dumps(cfg), retain=True):
                return False
            self._announced.add(eid)
        clean = {k: v for k, v in attrs.items() if k not in ("friendly_name", "icon", "device_class", "unit_of_measurement", "state_class")}
        ok = m.publish(self._topic(eid, "attr"), json.dumps(clean, default=str), retain=True)
        return m.publish(self._topic(eid, "state"), str(state), retain=True) and ok

    # --- the service's entry point ----------------------------------------------------
    def set_state(self, entity_id: str, state: str, attributes: dict) -> None:
        now = datetime.now(UTC)
        attrs = {**attributes, "updated_at": now.isoformat(timespec="seconds"), "valid_until": (now + self.valid).isoformat(timespec="seconds")}
        with self._lock:
            self.entities[entity_id] = {"state": str(state), "attrs": attrs, "at": now, "kind": kind_of(entity_id)}
        if entity_id in self.off:
            return
        if entity_id in SAFETY and self.failed_safe and str(state) == "on":
            return  # stays off until the loop works again (cleared by ok())
        if self.mode == "mqtt" and self._publish_mqtt(entity_id, state, attrs):
            return
        self.client.set_state(entity_id, state, attrs)

    # --- fail closed -------------------------------------------------------------
    def fail_safe(self, why: str) -> None:
        """Write the safety entities "off" now (start, stop, error, hung loop)."""
        if not self.failed_safe:
            LOG.warning("Safety entities set to off: %s", why)
        self.failed_safe = True
        for eid in SAFETY:
            if eid in self.off:
                continue
            prev = self.entities.get(eid, {}).get("attrs") or {"friendly_name": "Bifrost " + eid.split("_", 2)[-1].replace("_", " ")}
            attrs = {**prev, "reason": why}
            try:
                if self.mode == "mqtt" and self._publish_mqtt(eid, "off", attrs):
                    continue
                self.client.set_state(eid, "off", attrs)
            except Exception as err:  # noqa: BLE001 – best effort, HA may be gone
                LOG.warning("Could not write %s off: %s", eid, err)

    def ok(self) -> None:
        """An evaluation succeeded – the safety entities may follow the decision again."""
        self.failed_safe = False

    def stop(self) -> None:
        self.fail_safe("Bifrost stopped")
        if self.mqtt is not None:
            self.mqtt.stop(final=[(AVAIL, "offline", True)])

    # --- switching entities on/off -------------------------------------------------
    def set_enabled(self, entity_id: str, on: bool, confirm: bool = False) -> dict:
        if not OWN_ID.match(entity_id or ""):
            raise ValueError("invalid entity id")
        if not on and entity_id in SAFETY and not confirm:
            raise ValueError("safety entity: confirm needed")
        if on:
            self.off.discard(entity_id)
            self._announced.discard(entity_id)
            e = self.entities.get(entity_id)
            if e:
                self.set_state(entity_id, e["state"], e["attrs"])
        else:
            if entity_id in SAFETY:
                self.fail_safe("switched off by the owner")
            self.off.add(entity_id)
            self._remove(entity_id)
        self.store.set_value("entities_off", json.dumps(sorted(self.off)))
        return {"entity_id": entity_id, "on": on}

    def _remove(self, eid: str) -> None:
        domain, obj = eid.split(".", 1)
        if self.mqtt is not None and self.mqtt.connected:
            self.mqtt.publish(f"homeassistant/{domain}/{PREFIX}/{obj}/config", b"", retain=True)
            self.mqtt.publish(self._topic(eid, "state"), b"", retain=True)
            self.mqtt.publish(self._topic(eid, "attr"), b"", retain=True)
            self._announced.discard(eid)
        try:
            self.client.delete_state(eid)
        except Exception as err:  # noqa: BLE001 – may not exist as a REST state
            LOG.debug("No REST state to remove for %s: %s", eid, err)

    # --- clean-up of the old /api/states entities -------------------------------------
    def _migrate(self) -> None:
        if self.store.get_value("mqtt_migrated"):
            return
        removed = self.remove_leftovers()
        self.store.set_value("mqtt_migrated", datetime.now(UTC).isoformat())
        LOG.info("MQTT active – removed %d old Bifrost states", removed)

    def leftovers(self) -> list[str]:
        """bifrost_* states in HA that do not come from the registry (old /api/states entities)."""
        try:
            states = self.client.get_states()
            reg = {e.get("entity_id") for e in (self.client.registries() or {}).get("entities", [])}
        except Exception:  # noqa: BLE001
            return []
        return sorted(s["entity_id"] for s in states if OWN_ID.match(s.get("entity_id", "")) and s["entity_id"] not in reg)

    def remove_leftovers(self, only: str | None = None) -> int:
        if only is not None and not OWN_ID.match(only):
            raise ValueError("invalid entity id")
        n = 0
        for eid in [only] if only else self.leftovers():
            try:
                self.client.delete_state(eid)
                n += 1
            except Exception:  # noqa: BLE001
                LOG.warning("Could not remove %s", eid)
        return n

    # --- view for the Setup card -------------------------------------------------------
    def view(self) -> dict:
        with self._lock:
            rows = [
                {
                    "entity_id": eid,
                    "name": str(e["attrs"].get("friendly_name") or eid),
                    "kind": e["kind"],
                    "state": e["state"],
                    "updated": e["at"].isoformat(timespec="seconds"),
                    "on": eid not in self.off,
                    "safety": eid in SAFETY,
                }
                for eid, e in sorted(self.entities.items())
            ]
        for eid in sorted(self.off - set(self.entities)):
            rows.append({"entity_id": eid, "name": eid, "kind": kind_of(eid), "state": None, "updated": None, "on": False, "safety": eid in SAFETY})
        m = self.mqtt
        return {"mode": self.mode, "broker": self.broker, "connected": bool(m and m.connected), "error": (m.last_error if m else None), "entities": rows, "kinds": list(KINDS)}
