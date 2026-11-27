from datetime import UTC, datetime

from bifrost_app.brain import Brain
from bifrost_app.store import Store

T = datetime(2026, 3, 2, 22, 0, tzinfo=UTC)


def test_wrong_empty_correction_marks_somebody_unknown_inside(tmp_path):
    b = Brain(Store(str(tmp_path / "s.db")), {})
    res = b.correct("away", "home", T)
    assert b.gs.unknown_min == 1 and "guard:unknown" in res["learned"]
    assert Brain(b.store, {}).gs.unknown_min == 1  # saved


def test_unassigned_access_value_is_only_medium(tmp_path):
    b = Brain(Store(str(tmp_path / "s.db")), {})
    b.on_edge({"ts": T, "entity_id": "sensor.keypad_user", "kind": "access", "state": "unknown"})
    assert b.identity[-1]["strength"] == "medium"
    b.on_edge({"ts": T, "entity_id": "sensor.keypad_user", "kind": "access", "state": "household"})
    assert b.identity[-1]["strength"] == "strong"
