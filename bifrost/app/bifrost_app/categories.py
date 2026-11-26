"""Signal categories, roles and statuses used everywhere in Bifrost."""

from __future__ import annotations

CATEGORIES: dict[str, dict[str, str]] = {
    "motion": {"name": "Motion & presence", "icon": "🚶", "desc": "Presence, motion and mmWave sensors"},
    "openings": {"name": "Doors & windows", "icon": "🚪", "desc": "Front door, garage, windows"},
    "manual": {"name": "Manual activity", "icon": "👆", "desc": "Lights, blinds, buttons, thermostats used by a person"},
    "devices": {"name": "People & devices", "icon": "📱", "desc": "Phones and watches via Wi-Fi, Bluetooth, GPS"},
    "network": {"name": "Network", "icon": "🌐", "desc": "Clients per Wi-Fi, traffic"},
    "media": {"name": "Media", "icon": "🎵", "desc": "Speakers, TV, receiver playing"},
    "climate": {"name": "Air & climate", "icon": "🌡️", "desc": "CO₂, humidity, temperature"},
    "energy": {"name": "Energy", "icon": "⚡", "desc": "Base load, appliances, water"},
    "vehicles": {"name": "Vehicles & tags", "icon": "🚗", "desc": "Car beacon, tags, robots, pets"},
    "modes": {"name": "Modes", "icon": "🌙", "desc": "Sleep, night, away, guest modes"},
    "calendar": {"name": "Time & calendar", "icon": "📅", "desc": "Calendars, alarm clocks, weather, zones"},
    "security": {"name": "Security", "icon": "🔒", "desc": "Alarm state, locks, keypads"},
}

ROLES: dict[str, str] = {
    "Evidence": "says home or away",
    "Trigger": "starts a new check",
    "Context": "changes what is expected",
    "Blocker": "prevents “empty”",
    "Noise": "fakes activity – gets masked",
    "Truth": "proof that teaches Bifrost",
}

# Status of an entity inside Bifrost
STATUS_INCLUDED = "included"
STATUS_SUGGESTED = "suggested"
STATUS_UNKNOWN = "unknown"
STATUS_IGNORED = "ignored"
STATUSES = (STATUS_INCLUDED, STATUS_SUGGESTED, STATUS_UNKNOWN, STATUS_IGNORED)

# Confidence thresholds for automatic decisions of the classifier
AUTO_INCLUDE = 0.85
SUGGEST = 0.60


def is_valid_category(value: str | None) -> bool:
    """Return True if value is a known category id (or None)."""
    return value is None or value in CATEGORIES


def is_valid_role(value: str | None) -> bool:
    """Return True if value is a known role (or None)."""
    return value is None or value in ROLES
