from datetime import UTC, datetime, timedelta

import pytest

from bifrost_app.store import Store


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    yield s
    s.close()


def test_override_roundtrip(store):
    store.set_override("light.kitchen", "included", "manual", "Evidence")
    assert store.get_overrides()["light.kitchen"] == {"status": "included", "category": "manual", "role": "Evidence"}
    store.set_override("light.kitchen", "ignored", None, None)
    assert store.get_overrides()["light.kitchen"]["status"] == "ignored"


@pytest.mark.parametrize("args", [("x.y", "bad", None, None), ("x.y", "included", "nope", None), ("x.y", "included", None, "nope")])
def test_override_validation(store, args):
    with pytest.raises(ValueError):
        store.set_override(*args)


def test_history_and_prune(store):
    now = datetime.now(UTC)
    store.add_decision(now - timedelta(days=200), "away", 90, ["old"])
    store.add_decision(now - timedelta(hours=1), "home", 92, ["new"])
    assert [h["state"] for h in store.history(24)] == ["home"]
    assert store.prune() == 1
