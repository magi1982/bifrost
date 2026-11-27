import pytest

from bifrost_app.people import PeopleStore, ledger, public, slugify, validate
from bifrost_app.store import Store

IRK = "0123456789abcdef0123456789abcdef"


def test_validate_and_public_never_shows_keys():
    p = validate({"name": "Person A", "trackers": ["device_tracker.phone_a"], "irk": IRK.upper()})
    assert p.id == "person_a" and p.irk == IRK
    pub = public(p)
    assert "irk" not in pub and IRK not in str(pub)


@pytest.mark.parametrize(
    "body",
    [
        {"name": ""},
        {"name": "<script>"},
        {"name": "A", "kind": "boss"},
        {"name": "A", "trackers": ["light.x"]},
        {"name": "A", "trackers": "device_tracker.x"},
        {"name": "A", "calendars": ["sensor.x"]},
        {"name": "A", "irk": "xyz"},
        {"name": "A", "nfc_user": "a;b"},
        {"name": "A", "id": "../etc"},
    ],
)
def test_validate_rejects_bad_input(body):
    with pytest.raises(ValueError):
        validate(body)


def test_slugify_handles_umlauts():
    assert slugify("Kind Ö") == "kind_o"


def test_legacy_irk_moves_to_setup_keys_and_sources_are_kept(tmp_path):
    ps = PeopleStore(Store(str(tmp_path / "s.db")))
    ps.save({"name": "Person A", "irk": IRK, "trackers": ["device_tracker.a"]})
    assert ps.get("person_a").irk == ""
    keys = ps.irks()
    assert len(keys) == 1 and keys[0]["owner"] == "person_a" and keys[0]["key"] == "••••cdef" and IRK not in str(keys)
    ps.save({"id": "person_a", "name": "Person A renamed"})  # People tab sends name only
    assert ps.get("person_a").trackers == ["device_tracker.a"]
    with pytest.raises(ValueError):
        ps.save({"name": "Person A"})  # duplicate id
    assert ps.delete("person_a") and ps.all() == []


def people():
    return [
        validate({"name": "Person A", "trackers": ["device_tracker.a"]}),
        validate({"name": "Person B", "trackers": ["device_tracker.b"]}),
        validate({"name": "Kind A", "may_be_alone": False}),
        validate({"name": "Kind B", "may_be_alone": True}),
    ]


def test_ledger_child_who_never_stays_alone_leaves_with_adults():
    r = ledger(people()[:3], {"device_tracker.a": "not_home", "device_tracker.b": "not_home"})
    assert [x["state"] for x in r["people"]] == ["away", "away", "away"]
    assert r["people"][2]["reason"] == "never_alone" and r["all_away"] is True


def test_ledger_child_without_source_who_may_be_alone_stays_unclear():
    r = ledger(people(), {"device_tracker.a": "not_home", "device_tracker.b": "not_home"})
    assert r["all_away"] is False and r["unclear"] == ["Kind B"]


def test_ledger_unknown_people_block_empty_and_strength_is_reported():
    ps = people()[:2]
    r = ledger(ps, {"device_tracker.a": "not_home", "device_tracker.b": "not_home"}, unknown_min=1)
    assert r["all_away"] is False and r["unknown_min"] == 1
    r = ledger(ps, {"device_tracker.a": "home", "device_tracker.b": "unavailable"}, {"device_tracker.a": "medium"})
    assert r["people"][0]["strength"] == "medium" and r["people"][1]["state"] == "unclear"


def test_ledger_without_people_returns_none():
    assert ledger([], {})["all_away"] is None


def test_access_users_unique_and_shared_codes(tmp_path):
    ps = PeopleStore(Store(str(tmp_path / "a.db")))
    ps.save({"name": "Alex", "nfc_user": "Alex"})
    assert ps.get("alex").access_users == ["Alex"]
    with pytest.raises(ValueError):
        ps.save({"name": "Sam", "nfc_user": "alex"})
    assert ps.set_shared_access(["Family code"]) == ["Family code"]
    with pytest.raises(ValueError):
        ps.save({"name": "Mia", "nfc_user": "Family code"})
    with pytest.raises(ValueError):
        ps.set_shared_access(["Alex"])
    with pytest.raises(ValueError):
        ps.set_access_entities(["switch.x"])
    assert ps.set_access_entities(["sensor.door_user"]) == ["sensor.door_user"]


def test_access_match_whole_words_only():
    from bifrost_app.people import access_match

    assert access_match("Ben", "Unlocked by Ben")
    assert not access_match("Ben", "Benjamin")
    assert not access_match("", "Ben")


def test_owners_assigned_from_setup(tmp_path):
    ps = PeopleStore(Store(str(tmp_path / "o.db")))
    ps.save({"name": "Alex"})
    ps.save({"name": "Sam"})
    ps.set_owner("device_tracker.phone", "alex")
    ps.set_owner("calendar.family", "household")
    ps.set_owner("calendar.alex", "alex")
    assert ps.owners() == {"device_tracker.phone": "alex", "calendar.family": "household", "calendar.alex": "alex"}
    ps.set_owner("device_tracker.phone", "sam")  # moves, never two owners
    assert ps.get("alex").trackers == [] and ps.get("sam").trackers == ["device_tracker.phone"]
    ps.set_owner("calendar.family", "")
    assert "calendar.family" not in ps.owners()
    for bad in (("device_tracker.phone", "household"), ("light.x", "alex"), ("device_tracker.phone", "nobody"), ("bad id", "alex")):
        with pytest.raises(ValueError):
            ps.set_owner(*bad)


def test_access_values_person_household_ignore_denied_or_unassigned(tmp_path):
    ps = PeopleStore(Store(str(tmp_path / "m.db")))
    ps.save({"name": "Alex"})
    ps.map_access("Alex", "alex")
    ps.map_access("7", "alex")  # user number
    ps.map_access("Family code", "household")
    ps.map_access("Test tag", "ignore")
    assert ps.get("alex").access_users == ["Alex", "7"]
    assert ps.access_target("Alex") == "alex" and ps.access_target("7") == "alex"
    assert ps.access_target("Family code") == "household"
    assert ps.access_target("Test tag") == "ignore"
    assert ps.access_target("Zugang verweigert: Alex") == "denied"
    assert ps.access_target("Guest 3") is None  # authorised, just not assigned
    ps.map_access("7", "")
    assert ps.get("alex").access_users == ["Alex"]
    with pytest.raises(ValueError):
        ps.map_access("<x>", "alex")


def test_irk_keys_validation(tmp_path):
    ps = PeopleStore(Store(str(tmp_path / "k.db")))
    ps.save({"name": "Alex"})
    k = ps.save_irk({"label": "Alex iPhone", "key": IRK, "owner": "alex"})
    assert k["key"] == "••••cdef"
    ps.save_irk({"id": k["id"], "label": "Alex iPhone 15", "key": "", "owner": ""})  # empty key keeps it
    assert ps.irk_keys()[0]["key"] == IRK and ps.irk_keys()[0]["owner"] == ""
    for bad in ({"label": "x", "key": "123"}, {"label": "", "key": IRK}, {"label": "x", "key": IRK}):
        with pytest.raises(ValueError):
            ps.save_irk(bad)
    assert ps.delete_irk(k["id"]) == {"deleted": True}


def test_assigning_a_suggested_calendar_switches_it_on(tmp_path):
    from demo import build

    svc = build(str(tmp_path / "d.db"))
    svc.client.states.append({"entity_id": "calendar.work_b", "state": "off", "last_changed": "2026-01-01T00:00:00+00:00", "attributes": {"friendly_name": "Work B"}})
    svc.scan()
    assert svc.snap.entities["calendar.work_b"].status == "suggested"
    res = svc.set_owner("calendar.work_b", "person_b")
    assert res["switched_on"] and svc.snap.entities["calendar.work_b"].status == "included"
    assert "calendar.work_b" in svc.brain.people.get("person_b").calendars
