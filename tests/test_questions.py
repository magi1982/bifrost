from datetime import UTC, datetime, timedelta

import pytest

from bifrost_app.questions import Inbox
from bifrost_app.store import Store

T = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)


def inbox(tmp_path):
    return Inbox(Store(str(tmp_path / "s.db")))


def test_budget_grouping_and_safety(tmp_path):
    ib = inbox(tmp_path)
    for i in range(5):
        ib.ask("deviation", f"k{i}", {}, T)
    assert len(ib.open_items()) == 3  # daily budget for questions
    q = ib.ask("deviation", "k0", {"n": 2}, T)
    assert q["count"] == 2  # same thing again → grouped, not a new question
    assert ib.ask("suspicious_entry", "door|t", {}, T, safety=True)  # safety ignores the budget
    assert ib.open_items()[0]["type"] == "suspicious_entry"  # safety first
    assert ib.counts() == {"question": 4, "suggestion": 0}


def test_answers_dontknow_waits_and_reasks(tmp_path):
    ib = inbox(tmp_path)
    q = ib.ask("disturbance", "binary_sensor.hall", {"count": 4}, T)
    ib.answer(q["id"], "dontknow", None, T)
    assert ib.store.get_obj("question", q["id"])["status"] == "waiting"
    again = ib.ask("disturbance", "binary_sensor.hall", {"count": 5}, T + timedelta(days=1))
    assert again["status"] == "open"
    ib.answer(q["id"], "yes", "Ratten", T)
    assert ib.ask("disturbance", "binary_sensor.hall", {}, T + timedelta(days=2)) is None  # decided: never again


def test_answer_validation(tmp_path):
    ib = inbox(tmp_path)
    q = ib.ask("door_role", "binary_sensor.door", {}, T)
    with pytest.raises(ValueError):
        ib.answer(q["id"], "perhaps", None, T)
    with pytest.raises(ValueError):
        ib.answer(q["id"], "yes", "<b>", T)
    with pytest.raises(ValueError):
        ib.answer("nope", "yes", None, T)


def test_expiry_and_labels_explain_future_deviations(tmp_path):
    ib = inbox(tmp_path)
    q = ib.ask("deviation", "x", {}, T)
    assert ib.expire(T + timedelta(days=8)) == 1 and ib.store.get_obj("question", q["id"])["status"] == "expired"
    d = ib.deviation("contradiction", "phone_home_no_activity|person_a", {"hours": 3}, T)
    assert d["status"] == "open"
    ib.set_label("contradiction", "phone_home_no_activity|person_a", "Handy vergessen")
    ib.explain_deviations("phone_home_no_activity|person_a", "Handy vergessen")
    assert ib.deviations()[0]["status"] == "explained"
    d2 = ib.deviation("contradiction", "phone_home_no_activity|person_a", {}, T + timedelta(days=1))
    assert d2["status"] == "explained" and d2["label"] == "Handy vergessen"


def test_exceptions(tmp_path):
    ib = inbox(tmp_path)
    ib.add_exception("binary_sensor.hall", "Ratten")
    assert ib.exceptions()[0]["label"] == "Ratten"
    assert ib.remove_exception("binary_sensor.hall") and ib.exceptions() == []
