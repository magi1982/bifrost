"""0.19.1: below 70 % Bifrost names no state – it says "unclear" (also in Home Assistant)."""

from bifrost_app.brain import Brain
from bifrost_app.engine import ARRIVING, ASLEEP, AWAY, HOME, UNKNOWN, Decision


def _p(home, asleep, away):
    return {"home": home, "asleep": asleep, "away": away}


def test_home_below_70_is_unclear():
    d = Brain._apply_certainty(Decision(HOME, 66, ["Activity right now"]), _p(62, 4, 34))
    assert d.state == UNKNOWN and d.confidence == 66
    assert d.reasons[0].startswith("Only 66 % sure") and "Activity right now" in d.reasons


def test_home_counts_somebody_there_including_asleep():
    # 45 % awake + 40 % asleep = 85 % somebody is home → stays "home"
    assert Brain._apply_certainty(Decision(HOME, 85, []), _p(45, 40, 15)).state == HOME
    assert Brain._apply_certainty(Decision(HOME, 70, []), _p(66, 4, 30)).state == HOME  # exactly 70 % is enough


def test_asleep_and_away_need_70_too():
    assert Brain._apply_certainty(Decision(ASLEEP, 80, []), _p(30, 60, 10)).state == UNKNOWN
    assert Brain._apply_certainty(Decision(ASLEEP, 80, []), _p(10, 80, 10)).state == ASLEEP
    assert Brain._apply_certainty(Decision(AWAY, 90, []), _p(20, 15, 65)).state == UNKNOWN
    assert Brain._apply_certainty(Decision(AWAY, 90, []), _p(5, 5, 90)).state == AWAY


def test_transitions_and_missing_probabilities_are_left_alone():
    assert Brain._apply_certainty(Decision(ARRIVING, 60, []), _p(40, 0, 60)).state == ARRIVING
    assert Brain._apply_certainty(Decision(HOME, 60, []), {}).state == HOME
