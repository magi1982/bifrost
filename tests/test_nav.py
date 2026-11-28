"""The navigation table in index.html: every area and sub-tab has a German and an English label."""

import re
from pathlib import Path

HTML = (Path(__file__).parent.parent / "bifrost/app/bifrost_app/static/index.html").read_text(encoding="utf-8")


def _nav():
    block = HTML.split("var NAV=[", 1)[1].split("];", 1)[0]
    areas = re.findall(r'\["(\w+)","--n-\w+",\[(.*?)\]\]', block)
    return [(a, re.findall(r'\["(\w+)","(\w+)"\]', subs)) for a, subs in areas]


def _labels(lang):
    keys = set()
    for body in re.findall(r"Object\.assign\(TX\." + lang + r",\{(.*?)\}\);", HTML, re.S):
        keys |= set(re.findall(r"(\w+):", body))
    return keys


def test_six_areas_with_sub_tabs():
    nav = _nav()
    assert [a for a, _ in nav] == ["status", "house", "people", "recog", "safety", "setup"]
    assert all(subs for _, subs in nav)


def test_every_label_in_both_languages():
    for lang in ("de", "en"):
        keys = _labels(lang)
        for area, subs in _nav():
            assert "nav_" + area in keys, (lang, area)
            for sub, _view in subs:
                assert "sub_" + sub in keys, (lang, sub)


def test_sub_tabs_only_use_known_views():
    known = {"status", "house", "people", "recog", "dev", "questions", "balance", "setup"}
    for _, subs in _nav():
        assert {v for _, v in subs} <= known


def test_markers_exist_for_every_sub_tab():
    marked = set()
    for m in re.findall(r'SM\("([\w ]+)"\)', HTML):
        marked |= set(m.split())
    for area, subs in _nav():
        if area == "safety":  # one view per sub-tab, no markers needed
            continue
        for sub, _view in subs:
            assert sub in marked, sub
