from datetime import UTC, datetime, timedelta

from bifrost_app.service import BifrostService
from bifrost_app.store import Store

OLD = (datetime.now(UTC) - timedelta(hours=2)).isoformat()


class FakeClient:
    def __init__(self):
        self.published = {}
        self.states = [
            {"entity_id": "person.example_a", "state": "not_home", "last_changed": OLD, "attributes": {"friendly_name": "Person A"}},
            {"entity_id": "binary_sensor.hall_motion", "state": "off", "last_changed": OLD, "attributes": {"device_class": "motion", "friendly_name": "Hall motion"}},
            {"entity_id": "update.core", "state": "off", "last_changed": OLD, "attributes": {}},
            {"entity_id": "sensor.bifrost_home_status", "state": "away", "last_changed": OLD, "attributes": {}},
        ]

    def get_states(self):
        return self.states

    def registries(self):
        return {
            "entities": [{"entity_id": "binary_sensor.hall_motion", "platform": "hue", "area_id": "hall"}, {"entity_id": "light.disabled_lamp", "platform": "hue", "disabled_by": "user"}],
            "devices": [],
            "areas": [{"area_id": "hall", "name": "Hall"}],
        }

    def get_calendar(self, eid, start, end):
        return getattr(self, "calendar_entries", [])

    def set_state(self, eid, state, attrs):
        self.published[eid] = (state, attrs)


def make(tmp_path, **opts):
    client = FakeClient()
    return BifrostService(client, Store(str(tmp_path / "s.db")), {"shadow_mode": True, "publish_entities": True, **opts}), client


def test_scan_classifies_and_skips_own_entities(tmp_path):
    svc, _ = make(tmp_path)
    svc.scan()
    ents = svc.snap.entities
    assert "sensor.bifrost_home_status" not in ents
    assert ents["binary_sensor.hall_motion"].info.area == "Hall"
    assert ents["light.disabled_lamp"].info.disabled and not ents["light.disabled_lamp"].info.available
    view = svc.entities_view()["summary"]
    assert view["total"] == 4 and view["disabled_in_ha"] == 1


def make_warm(tmp_path, **opts):
    """A service that has been running for a while (past the guard's start-up hold)."""
    svc, client = make(tmp_path, **opts)
    svc.brain.started_at -= timedelta(hours=1)
    return svc, client


def test_evaluate_publishes_entities(tmp_path):
    svc, client = make_warm(tmp_path)
    svc.scan()
    d = svc.evaluate()
    assert d.state == "away"
    assert client.published["binary_sensor.bifrost_house_empty"][0] == "on"
    assert client.published["sensor.bifrost_home_status"][1]["attribution"] == "Bifrost (shadow mode)"
    assert svc.status_view()["decision"]["label"] == "Away"


def test_publish_can_be_disabled(tmp_path):
    svc, client = make(tmp_path, publish_entities=False)
    svc.scan()
    svc.evaluate()
    assert client.published == {}


def test_user_override_persists_across_scans(tmp_path):
    svc, _ = make(tmp_path)
    svc.scan()
    svc.update_entity("binary_sensor.hall_motion", "ignored", None, None)
    svc.scan()
    e = svc.snap.entities["binary_sensor.hall_motion"]
    assert e.status == "ignored" and e.user_set


def test_unknown_entity_override_is_not_stored(tmp_path):
    import pytest

    svc, _ = make(tmp_path)
    svc.scan()
    with pytest.raises(KeyError):
        svc.update_entity("light.does_not_exist", "included", None, None)
    assert "light.does_not_exist" not in svc.store.get_overrides()


def test_vanished_entity_lowers_data_health(tmp_path):
    svc, client = make(tmp_path)
    svc.scan()
    client.states = [s for s in client.states if s["entity_id"] != "binary_sensor.hall_motion"]
    d = svc.evaluate()
    assert d.data_health < 100 and not d.house_empty


def test_guest_mode_persists_and_blocks(tmp_path):
    svc, client = make(tmp_path)
    svc.scan()
    svc.set_guest_mode(True)
    assert svc.evaluate().state == "home"
    assert client.published["binary_sensor.bifrost_guest_mode"][0] == "on"
    svc2 = BifrostService(client, svc.store, {})
    assert svc2.settings.guest_mode


def test_views_and_extra_entities(tmp_path):
    svc, client = make(tmp_path)
    svc.scan()
    svc.evaluate()
    assert client.published["sensor.bifrost_person_example_a"][0] == "away"
    assert client.published["binary_sensor.bifrost_anomaly"][0] == "off"


def test_expected_return_from_history(tmp_path):
    from datetime import timedelta

    svc, _ = make(tmp_path)
    now = datetime.now(UTC).replace(hour=8, minute=0, second=0, microsecond=0)
    for w in (1, 2, 3):
        day = now - timedelta(days=7 * w)
        svc.store.add_decision(day.replace(hour=7), "away", 90, [])
        svc.store.add_decision(day.replace(hour=17, minute=30 + w), "home", 90, [])
    ret = svc.expected_return(now)
    assert ret is not None and ret.hour == 17 and 30 <= ret.minute <= 33


def test_calendar_learning_without_titles(tmp_path):
    import json
    from datetime import timedelta

    svc, client = make(tmp_path)
    client.states.append({"entity_id": "calendar.example_work", "state": "on", "last_changed": OLD, "attributes": {"message": "Office day Zurich"}})
    svc.scan()
    svc.update_entity("calendar.example_work", "included", None, None)
    entries = []
    base = datetime.now(UTC).replace(hour=8, minute=0, second=0, microsecond=0) - timedelta(days=10)
    for i in range(6):
        st = base + timedelta(days=i)
        # what hindsight sees: activity, the phone leaves, quiet, the phone comes back, activity
        for m in (-12, -11):
            svc.store.add_event(st + timedelta(minutes=m), "binary_sensor.hall_motion", "Hall", "motion", "Evidence", "on", kind="on")
        svc.store.add_event(st - timedelta(minutes=5), "person.example_a", "Person A", "devices", "Evidence", "not_home", kind="away")
        svc.store.add_event(st + timedelta(hours=8), "person.example_a", "Person A", "devices", "Evidence", "home", kind="home")
        for m in (481, 482):
            svc.store.add_event(st + timedelta(minutes=m), "binary_sensor.hall_motion", "Hall", "motion", "Evidence", "on", kind="on")
        entries.append({"summary": "Office day Zurich", "start": {"dateTime": st.isoformat()}, "end": {"dateTime": (st + timedelta(hours=8)).isoformat()}})
    client.calendar_entries = entries
    svc.learn_job(datetime.now(UTC))
    view = svc.calendars_view()
    assert view["read"]["calendars"][0]["entries"] == 6 and view["read"]["calendars"][0]["ok"]
    work = svc.status_view()["work"]
    assert work["events_24h"] == 0 and work["last_learn"] and view["next_learn"]
    kws = {k["word"]: k for k in view["words"]}
    assert kws["office"]["effects"]["house_empty"] == 1.0
    raw = json.dumps(svc.store.get_obj("model", "calwords"))
    assert "Office day Zurich" not in raw  # full titles are never stored
    d = svc.evaluate()
    assert any("usually nobody home" in r for r in d.reasons)
    assert not any("Office day Zurich" in r for r in d.reasons)  # the title itself is never echoed


def test_calendar_learning_can_be_switched_off(tmp_path):
    svc, client = make(tmp_path, learn_calendars=False)
    svc.scan()
    client.calendar_entries = [{"summary": "x", "start": {"dateTime": "2026-01-01T08:00:00+00:00"}, "end": {"dateTime": "2026-01-01T09:00:00+00:00"}}]
    svc.learn_job(datetime.now(UTC))
    assert svc.store.get_calendar_stats() == {}


def test_right_after_start_bifrost_never_says_empty(tmp_path):
    svc, client = make(tmp_path)
    svc.scan()
    d = svc.evaluate()
    assert d.state == "unknown" and any("just started" in r for r in d.reasons)
    assert client.published["binary_sensor.bifrost_house_empty"][0] == "off"


def test_guard_failure_fails_closed(tmp_path, monkeypatch):
    svc, client = make_warm(tmp_path, alarm_signal=True)
    svc.scan()

    def boom(*a, **k):
        raise RuntimeError("guard broke")

    monkeypatch.setattr(svc.brain, "tick", boom)
    d = svc.evaluate()
    assert d.state == "unknown" and "Safety check failed" in d.reasons[0]
    assert svc.extra["checks"][0] == {"id": "guard_error", "ok": False, "detail": None, "active": True}
    assert client.published["binary_sensor.bifrost_empty_confirmed"][0] == "off"


def test_guard_state_survives_a_restart(tmp_path):
    svc, _ = make_warm(tmp_path)
    svc.scan()
    svc.brain.gs.unknown_min = 2
    svc.evaluate()
    again = BifrostService(FakeClient(), svc.store, {})
    assert again.brain.gs.unknown_min == 2


def test_catalog_counts_by_ha_standards(tmp_path):
    svc, client = make(tmp_path)
    client.states += [
        {"entity_id": "device_tracker.iphone_ble", "state": "home", "last_changed": OLD, "attributes": {"source_type": "bluetooth_le"}},
        {"entity_id": "alarm_control_panel.house", "state": "disarmed", "last_changed": OLD, "attributes": {}},
        {"entity_id": "vacuum.robot", "state": "docked", "last_changed": OLD, "attributes": {}},
    ]
    svc.scan()
    kinds = {k["kind"]: k for k in svc.catalog_view()["kinds"]}
    assert kinds["motion"]["found"] == 1 and kinds["phones"]["found"] == 1
    assert kinds["bluetooth"]["found"] == 1 and kinds["alarm"]["found"] == 1 and kinds["robots_cars"]["found"] == 1
    assert kinds["cameras"]["found"] == 0


def test_entity_detail_shows_data_history_and_hides_secrets(tmp_path):
    svc, client = make_warm(tmp_path)
    attrs = {"access_token": "SECRET", "entity_picture": "/api/x?token=SECRET", "friendly_name": "Door cam"}
    client.states.append({"entity_id": "camera.door", "state": "idle", "last_changed": OLD, "attributes": attrs})
    client.get_history = lambda eid, a, b: [{"state": "on", "last_changed": OLD}, {"state": "off", "last_changed": OLD}]
    svc.scan()
    svc.evaluate()
    d = svc.entity_detail("binary_sensor.hall_motion")
    assert d["attributes"]["device_class"] == "motion" and len(d["history"]) == 2 and d["entity"]["entity_id"] == "binary_sensor.hall_motion"
    cam = svc.entity_detail("camera.door")
    assert "SECRET" not in str(cam) and cam["attributes"]["friendly_name"] == "Door cam"
    import pytest

    with pytest.raises(KeyError):
        svc.entity_detail("light.unknown")
    del client.get_history  # a client without history still works
    assert svc.entity_detail("binary_sensor.hall_motion")["history"] == []


def test_new_entities_are_marked_and_announced_once(tmp_path):
    svc, client = make(tmp_path)
    sent = []
    client.notify_services = lambda: ["mobile_app_phone_a"]
    client.notify = lambda service, title, message: sent.append((service, message))
    svc.scan()
    assert not any(e.new for e in svc.snap.entities.values())  # the first scan only remembers
    svc.set_notify("mobile_app_phone_a")
    client.states.append({"entity_id": "binary_sensor.new_motion", "state": "off", "last_changed": OLD, "attributes": {"device_class": "motion", "friendly_name": "New motion"}})
    svc.scan()
    assert svc.snap.entities["binary_sensor.new_motion"].new and svc.entities_view()["summary"]["new"] == 1
    assert len(sent) == 1 and "New motion" in sent[0][1]
    svc.scan()
    assert len(sent) == 1  # announced only once
    assert svc.mark_seen("binary_sensor.new_motion") == {"seen": 1} and not svc.snap.entities["binary_sensor.new_motion"].new
    import pytest

    with pytest.raises(ValueError):
        svc.set_notify("mobile_app_other")
    with pytest.raises(ValueError):
        svc.mark_seen("../x")
    assert svc.test_notification() == {"sent": True}
