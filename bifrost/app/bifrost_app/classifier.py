"""Sensor configurator: guesses category, role and confidence for any entity.

The classifier only uses metadata Home Assistant already has (domain, device
class, name, area, integration, unit). It never needs a cloud service.
Every guess comes with plain-language reasons so the user can follow it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .categories import AUTO_INCLUDE, STATUS_IGNORED, STATUS_INCLUDED, STATUS_SUGGESTED, STATUS_UNKNOWN, SUGGEST


@dataclass
class EntityInfo:
    """Metadata of one Home Assistant entity."""

    entity_id: str
    name: str = ""
    device_class: str | None = None
    area: str | None = None
    integration: str | None = None
    unit: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    disabled: bool = False
    disabled_by: str | None = None
    available: bool = True

    @property
    def domain(self) -> str:
        return self.entity_id.split(".", 1)[0]

    @property
    def text(self) -> str:
        """All human readable text, lower case, for keyword matching."""
        parts = [self.entity_id, self.name, self.area or "", self.integration or "", self.manufacturer or "", self.model or ""]
        return " ".join(parts).lower()


@dataclass
class Classification:
    """Result of the classifier for one entity."""

    category: str | None
    role: str | None
    confidence: float
    reasons: list[str] = field(default_factory=list)
    relevant: bool = True

    @property
    def status(self) -> str:
        """Default status inside Bifrost, before the user changes anything."""
        if not self.relevant:
            return STATUS_IGNORED
        if self.confidence >= AUTO_INCLUDE:
            return STATUS_INCLUDED
        if self.confidence >= SUGGEST:
            return STATUS_SUGGESTED
        return STATUS_UNKNOWN


def _kw(*words: str) -> re.Pattern[str]:
    return re.compile(r"(" + "|".join(words) + r")")


KW_SLEEP = _kw("sleep", "schlaf", "night", r"(?<!weih)nacht(?!tisch)", "tiefschlaf", r"\bbed\b", r"\bbett\b")
KW_AWAY = _kw("away", "abwesend", "vacation", "holiday", "urlaub", "ferien")
KW_GUEST = _kw("guest", "gast", "gäste", "gaste", "gaeste")
KW_ROOM_NOT_MODE = _kw(r"\bwc\b", "_wc", "toilet", "zimmer", "room", "bad")
KW_MODE = _kw("mode", "modus", "aktiv", "active", r"\bon\b")
KW_KIDS = _kw("kid", "kids", "kinder", "child")
TESLA_BLE = re.compile(r"(^|[._ ])s[0-9a-f]{16}c([._ ]|$)", re.I)  # Teslas advertise "S" + 16 hex + "C" via Bluetooth
KW_IDENTITY = _kw(
    "last.?user",
    "letzte[rn]?.?benutzer",
    "zuletzt",
    r"\bbenutzer\b",
    r"\buser\b",
    "nfc",
    "fingerprint",
    "fingerabdruck",
    "code.?touch",
    "keypad",
    "zutritt",
    "access",
    "rfid",
    "transponder",
    "unlocked.?by",
    "ge(ö|oe)ffnet.?von",
)
KW_FRONT = _kw("front.?door", "haust", "entrance", "eingang", "garage", "terrass", "terrace", "sitzplatz", "balkon", "balcony", "patio")
KW_DOORNAME = _kw("tür", "tuer", r"\btor\b", "garagentor", "gartentor", "door", r"\bgate\b", "schiebe")
KW_FRIDGE = _kw("fridge", "kühlschrank", "kuehlschrank", "kuhlschrank", "freezer", "gefrier")
KW_DOORBELL = _kw("doorbell", "klingel", "ring")
KW_PHONE = _kw("phone", "iphone", "handy", "pixel", "galaxy", "android", "smartphone")
KW_WATCH = _kw("watch", "uhr", "fitbit", "garmin")
KW_STATIONARY = _kw("ipad", "tablet", "notebook", "laptop", "desktop", "printer", "drucker", "nas", "synology", "server", "macbook", "-pc", "_pc", "win11")
KW_TV = _kw("tv", "fernseh", "fire_tv", "appletv", "apple_tv", "receiver", "marantz", "yamaha", "sonos", "console", "playstation", "ps5", "xbox", "switch_console", "game")
KW_WEARABLE = _kw("buds", "airpods", "headphone", "kopfh", "club950", "earbuds", "fitbit", "watch", "versa")
KW_ROBOT_DETAIL = _kw(
    "zeit",
    "time",
    "filter",
    "burste",
    "bürste",
    "brush",
    "gesamt",
    "total",
    "bereich",
    "area",
    "count",
    "zahl",
    "lade",
    "charg",
    "sensor_dirty",
    "error",
    "fehler",
    "batter",
    "wasser",
    "storen",
    "stören",
    "dnd",
)
KW_INFRA = _kw(
    "shelly",
    "v_zug",
    "vzug",
    "v-zug",
    "bridge",
    "gateway",
    "ventcube",
    "backofen",
    "tumbler",
    "miniserver",
    "loxone",
    "zisterne",
    "whirlpool",
    "wallbox",
    "heizung",
    "camera",
    "kamera",
    "doorbell",
    "access_point",
    r"\bap\b",
    "unifi_switch",
    "esp",
    "sonos",
    "homepod",
    "echo",
    "nest",
)
KW_WEATHER = _kw("regen", "rain", "sonnenschein", "sunshine", "wind", "frost", "dämmerung", "daemmerung", "twilight")
KW_CAR = _kw(r"\bcar\b", "_car", "tesla", r"\bauto\b", "vehicle", "ibeacon")
KW_PET = _kw(r"\bpet", r"\bcat\b", "katze", r"\bdog\b", "hund", "cat_flap", "katzenklappe", "pet_door")
KW_ROBOT = _kw("vacuum", "robot", "roborock", "roomba", "mower", "mäher", "maeher", "poolroboter")
KW_BIGLOAD = _kw(
    "pool",
    "whirlpool",
    "jacuzzi",
    "heat.?pump",
    "wärmepumpe",
    "waermepumpe",
    "warmepumpe",
    "wallbox",
    "pv",
    "solar",
    "photovoltaik",
    "batter",
    "grid",
    "netz",
    "irrigation",
    "bewässerung",
    "bewaesserung",
    "zisterne",
)
KW_APPLIANCE = _kw("dishwasher", "geschirr", "coffee", "kaffee", "kettle", "wasserkocher", "oven", "backofen", "steamer", "washing", "wasch", "dryer", "tumbler", "toothbrush", "zahnbürste")
KW_OUTDOOR = _kw("garden", "garten", "outdoor", "aussen", "außen", "terrace", "terrasse", "patio", "sitzplatz", "pergola", "driveway", "einfahrt")
KW_ALARM_CLOCK = _kw("next_alarm", "nachster_wecker", "nächster_wecker", "next alarm", "wecker", "alarm_clock")
KW_BIRTHDAY = _kw("birthday", "geburtstag", "holidays_ch", "feiertag")
KW_CLIENTS = _kw("clients", "client_count")
KW_PRESENCE = _kw("presence", "präsenz", "prasenz", "occupancy", "motion", "bewegung")
KW_SYSTEM = _kw("cpu", "memory", "disk", "uptime", "firmware", "rssi", "signal", "battery", "update", "ip_address", "last_restart", "temperature_chip", "wifi_signal")

NETWORK_SWITCH_INTEGRATIONS = {"unifi", "unifiprotect", "fritz", "tplink_omada", "mikrotik", "pihole", "adguard", "opnsense", "pfsense"}

IRRELEVANT_DOMAINS = {
    "update",
    "button",
    "number",
    "select",
    "text",
    "input_text",
    "input_number",
    "input_button",
    "input_select",
    "input_datetime",
    "sun",
    "conversation",
    "tts",
    "stt",
    "wake_word",
    "image",
    "notify",
    "siren",
    "valve",
    "fan",
    "humidifier",
    "water_heater",
    "remote",
    "camera",
    "todo",
    "event_log",
    "assist_satellite",
    "ai_task",
    "automation",
    "script",
    "scene",
    "group",
    "counter",
    "timer",
    "schedule",
    "tag",
}
IRRELEVANT_BINARY_CLASSES = {
    "battery",
    "battery_charging",
    "connectivity",
    "problem",
    "update",
    "running",
    "plug",
    "power",
    "safety",
    "smoke",
    "gas",
    "carbon_monoxide",
    "heat",
    "cold",
    "moisture",
    "light",
    "tamper",
    "lock",
}


def classify(e: EntityInfo) -> Classification:  # noqa: C901 – a flat rule list is the clearest form here
    """Guess category, role and confidence for one entity."""
    d, dc, t = e.domain, (e.device_class or "").lower(), e.text
    outdoor = bool(KW_OUTDOOR.search(t))

    def c(cat: str | None, role: str | None, conf: float, *reasons: str, relevant: bool = True) -> Classification:
        rs = list(reasons)
        if e.disabled:
            who = e.disabled_by or "user"
            rs.append(
                {
                    "integration": "Disabled by its integration in Home Assistant (often devices that were offline during setup) – enable it there: Settings → Entities",
                    "user": "Disabled by you in Home Assistant – enable it there: Settings → Entities",
                    "device": "Its device is disabled in Home Assistant – enable the device there: Settings → Devices",
                    "config_entry": "Its integration is disabled in Home Assistant – enable the integration there: Settings → Integrations",
                }.get(who, "Disabled in Home Assistant – enable it there first")
            )
        if not e.available:
            rs.append("Currently unavailable – check the device")
        return Classification(cat, role, round(conf, 2), rs, relevant)

    # --- clearly irrelevant ---------------------------------------------------
    if d in {"sensor", "input_text", "text", "event"} and KW_IDENTITY.search(t) and dc not in {"timestamp", "battery", "signal_strength"}:
        return c("security", "Identity", 0.75, "Name says it reports who unlocked (keypad, NFC, fingerprint)", "Assign the reported users to people in Setup")
    if d in IRRELEVANT_DOMAINS:
        return c(None, None, 0.0, f"Domain “{d}” says nothing about presence", relevant=False)
    if d == "sensor" and KW_SYSTEM.search(t) and dc not in {"carbon_dioxide", "humidity"}:
        return c(None, None, 0.0, "System or diagnostic value", relevant=False)

    # --- people & devices -----------------------------------------------------
    if d == "person":
        return c("devices", "Evidence", 0.95, "Home Assistant person – combines this person's trackers")
    if d == "device_tracker":
        if TESLA_BLE.search(e.entity_id) or TESLA_BLE.search(e.name or ""):
            return c("vehicles", "Evidence", 0.8, "Tesla via Bluetooth – the car is close to the house", "Whether someone came home with it is learned by the pattern recognition")
        if KW_CAR.search(t):
            return c("vehicles", "Evidence", 0.8, "Tracker of a car or beacon")
        if KW_STATIONARY.search(t) or KW_INFRA.search(t):
            return c(None, None, 0.0, "Stationary device (tablet, computer, printer) – stays at home", relevant=False)
        if KW_TV.search(t):
            return c("media", "Evidence", 0.65, "TV or console online – somebody may use it")
        if KW_WATCH.search(t):
            return c("devices", "Evidence", 0.8, "Watch – carried by a person")
        if KW_PHONE.search(t):
            return c("devices", "Evidence", 0.9, "Name looks like a phone", "Phones leave the house with their owner")
        if "unifi_default" in t or re.search(r"([0-9a-f]{2}_){5}[0-9a-f]{2}", t):
            return c("devices", "Evidence", 0.4, "Unknown device, only an address", "Could be a phone with a rotating private address")
        return c("devices", "Evidence", 0.5, "Network or GPS tracker – unclear if it moves with a person")

    # --- calendars, time, context --------------------------------------------
    if d == "calendar":
        if KW_BIRTHDAY.search(t):
            return c(None, None, 0.0, "Birthday / holiday calendar – says nothing about presence", relevant=False)
        return c("calendar", "Context", 0.8, "Calendar – planned absences")
    if d == "weather":
        return c("calendar", "Context", 0.6, "Weather changes how likely people stay home")
    if d == "zone":
        return c("calendar", "Context", 0.7, "Zone for GPS trackers")
    if d == "sensor" and (KW_ALARM_CLOCK.search(t) or (dc == "timestamp" and "alarm" in t)):
        return c("calendar", "Context", 0.75, "Next alarm clock – tells when someone gets up")

    # --- security ------------------------------------------------------------
    if d == "alarm_control_panel":
        return c("security", "Truth", 0.9, "Alarm panel – armed away is proof the house is empty")
    if d == "lock":
        return c("security", "Evidence", 0.9, "Lock – locked from outside is a strong “empty” clue", "Bifrost also reads who unlocked it, if the lock reports it")

    # --- noise sources -------------------------------------------------------
    if KW_ROBOT.search(t) and d in {"sensor", "binary_sensor"} and KW_ROBOT_DETAIL.search(t):
        return c(None, None, 0.0, "Robot maintenance or statistics value", relevant=False)
    if d == "vacuum" or (KW_ROBOT.search(t) and d in {"switch", "binary_sensor", "sensor", "lawn_mower"}):
        return c("vehicles", "Noise", 0.9, "Robot – moves when nobody is home, masks motion")
    if d == "lawn_mower":
        return c("vehicles", "Noise", 0.9, "Robot mower – not a person")
    if KW_PET.search(t) and d in {"binary_sensor", "sensor", "event"}:
        return c("vehicles", "Noise", 0.7, "Pet related – activity of an animal, not a person")

    # --- modes & helpers -----------------------------------------------------
    if d == "switch" and (e.integration or "").lower() in NETWORK_SWITCH_INTEGRATIONS:
        return c(None, None, 0.0, "Network switch (Wi-Fi, port, firewall rule) – says nothing about presence", relevant=False)
    if d in {"switch", "input_boolean"}:
        if KW_GUEST.search(t) and (KW_MODE.search(t) or not KW_ROOM_NOT_MODE.search(t)):
            return c("modes", "Blocker", 0.85, "Guest mode – house must not be “empty”")
        if KW_SLEEP.search(t) and not re.search(r"light|licht", t):
            return c("modes", "Blocker", 0.9, "Sleep or night mode – people are home")
        if KW_AWAY.search(t):
            return c("modes", "Context", 0.85, "Away / holiday mode – long absence expected")
        if KW_BIGLOAD.search(t) or KW_ROBOT.search(t):
            return c("energy", "Noise", 0.6, "Large automatic load – runs without people")
        if KW_APPLIANCE.search(t):
            return c("energy", "Evidence", 0.65, "Appliance switch – usually started by a person")
        return c(None, None, 0.0, "Switch without a clear meaning", relevant=False)

    # --- media ---------------------------------------------------------------
    if d == "media_player":
        if KW_WEARABLE.search(t):
            return c(None, None, 0.0, "Headphones or watch – plays wherever the person is, not only at home", relevant=False)
        return c("media", "Evidence", 0.85, "Media playing – somebody listens or watches", "Can also be started by automations, so it is not a blocker")

    # --- manual activity -----------------------------------------------------
    if d == "light":
        return c("manual", "Evidence", 0.55, "Light – only counts when a person switched it (not an automation)")
    if d == "cover":
        return c("manual", "Evidence", 0.45, "Blind – only counts when a person moved it")
    if d == "climate":
        return c("manual", "Evidence", 0.4, "Thermostat – a manual change means a person")
    if d == "event":
        if KW_DOORBELL.search(t):
            return c("openings", "Noise", 0.8, "Doorbell – a visitor, not the family")
        return c("manual", "Evidence", 0.8, "Button or remote event – pressed by a person")

    # --- binary sensors ------------------------------------------------------
    if d == "binary_sensor":
        if dc in IRRELEVANT_BINARY_CLASSES:
            return c(None, None, 0.0, f"Device class “{dc}” says nothing about presence", relevant=False)
        if KW_WEATHER.search(t) and dc not in {"motion", "occupancy", "presence", "door", "window", "opening"}:
            return c(None, None, 0.0, "Weather value – says nothing about presence", relevant=False)
        if KW_FRIDGE.search(t):
            return c("manual", "Evidence", 0.85, "Fridge or freezer door – opened only by people")
        if KW_DOORBELL.search(t):
            return c("openings", "Noise", 0.8, "Doorbell – a visitor, not the family")
        if dc in {"occupancy", "presence", "motion"} or (not dc and KW_PRESENCE.search(t)):
            if outdoor:
                return c("motion", "Evidence", 0.55, f"Device class: {dc or 'presence'}", "Outdoors – wind, animals and passers-by trigger it")
            return c("motion", "Evidence", 0.92, f"Device class: {dc or 'presence (from name)'}", "Inside the house – a strong presence signal")
        if dc in {"door", "garage_door"} or (dc in {"window", "opening"} and KW_DOORNAME.search(t)):
            if KW_FRONT.search(t):
                return c("openings", "Trigger", 0.95, f"Device class: {dc}", "Main entrance – starts a new check")
            return c("openings", "Evidence", 0.75, f"Device class: {dc}")
        if dc in {"window", "opening"}:
            return c("openings", "Evidence", 0.85, f"Device class: {dc}", "Opened from inside means someone is home")
        if dc == "sound":
            return c("motion", "Evidence", 0.6, "Sound detected – could be a person or a device")
        if dc == "vibration":
            return c(None, None, 0.5, "Vibration – a person or a machine?")
        if KW_SLEEP.search(t):
            return c("modes", "Blocker", 0.85, "Bed or sleep sensor – people are home")
        return c(None, None, 0.3, "Binary sensor without a known meaning")

    # --- sensors ---------------------------------------------------------------
    if d == "sensor":
        if KW_CLIENTS.search(t):
            if KW_GUEST.search(t):
                return c("network", "Blocker", 0.85, "Clients in the guest Wi-Fi – visitors are here")
            if KW_KIDS.search(t):
                return c("network", "Evidence", 0.8, "Clients in the kids Wi-Fi")
            if "iot" in t:
                return c(None, None, 0.0, "IoT network – devices stay at home", relevant=False)
            return c("network", "Evidence", 0.6, "Number of Wi-Fi clients")
        if dc == "carbon_dioxide" or "co2" in t:
            return c("climate", "Evidence", 0.65, "CO₂ rises when people are in the room", "Slow – minutes of delay")
        if dc == "humidity":
            return c("climate", "Evidence", 0.5, "Humidity jumps when someone showers")
        if dc in {"temperature", "pressure", "illuminance", "pm25", "pm10", "volatile_organic_compounds"}:
            return c(None, None, 0.0, f"{dc} – too slow or unrelated to presence", relevant=False)
        if (e.unit or "").lower() in {"l/min", "l/h", "m³/h", "m3/h"} or "water" in t or "wasser" in t:
            return c("energy", "Evidence", 0.65, "Water flow – taps and showers are used by people")
        if dc in {"power", "energy", "current"} or (e.unit or "") in {"W", "kW", "kWh", "Wh", "A"}:
            if KW_BIGLOAD.search(t):
                return c("energy", "Noise", 0.6, "Large automatic load (pool, heat pump, PV, wallbox) – not a person")
            if KW_APPLIANCE.search(t):
                return c("energy", "Evidence", 0.75, "Appliance power – started by a person")
            return c("energy", "Evidence", 0.45, "Power value – useful only as a spike above the base load")
        return c(None, None, 0.0, "Sensor without a known link to presence", relevant=False)

    return c(None, None, 0.0, f"Domain “{d}” – no rule yet", relevant=False)
