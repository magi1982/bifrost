"""Language setting and translations."""

import pytest

from bifrost_app.i18n import DE, normalize, tr


def test_exact_and_template_translation():
    assert tr("Home", "de") == "Daheim"
    assert tr("Home", "en") == "Home"
    assert tr("Front door is home", "de") == "Front door ist daheim"
    assert tr("Theme: dark", "de") == "Design: Dunkel"
    assert tr("Something unknown", "de") == "Something unknown"


def test_every_template_keeps_its_placeholders():
    for k, v in DE.items():
        assert k.count("{}") == v.count("{}"), k


def test_normalize_language_tags():
    assert normalize("de-CH") == "de"
    assert normalize("en-GB") == "en"
    assert normalize(None) == "en"


def test_language_from_home_assistant_and_manual_switch(tmp_path):
    from demo import build

    svc = build(str(tmp_path / "d.db"))
    assert svc.language == "de"  # demo HA reports German
    assert svc.set_language("en") == {"language": "en"}
    assert svc.store.get_value("language") == "en"
    with pytest.raises(ValueError):
        svc.set_language("fr")
