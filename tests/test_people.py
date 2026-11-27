import pytest

from bifrost_app.people import PeopleStore, ledger, public, slugify, validate
from bifrost_app.store import Store

IRK = "0123456789abcdef0123456789abcdef"


def test_validate_and_mask_irk():
    p = validate({"name": "Person A", "trackers": ["device_tracker.phone_a"], "irk": IRK.upper()})
    assert p.id == "person_a" and p.irk == IRK
    pub = public(p)
    assert pub["irk"] == "••••cdef" and pub["has_irk"] and IRK not in str(pub)


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


def test_store_keeps_irk_when_field_left_empty(tmp_path):
    ps = PeopleStore(Store(str(tmp_path / "s.db")))
    ps.save({"name": "Person A", "irk": IRK})
    ps.save({"id": "person_a", "name": "Person A", "irk": ""})
    assert ps.get("person_a").irk == IRK
    ps.save({"id": "person_a", "name": "Person A", "irk": "-"})
    assert ps.get("person_a").irk == ""
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
