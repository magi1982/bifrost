"""Home Assistant shows the changelog from the app folder – keep it identical to the repository one."""

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_app_changelog_matches_repository_changelog():
    assert (ROOT / "bifrost" / "CHANGELOG.md").read_text() == (ROOT / "CHANGELOG.md").read_text()


def test_changelog_has_entry_for_current_version():
    version = re.search(r'^version: "([^"]+)"', (ROOT / "bifrost" / "config.yaml").read_text(), re.M).group(1)
    assert f"## [{version}]" in (ROOT / "CHANGELOG.md").read_text()


def test_apparmor_profile_is_present_and_not_too_strict():
    text = (ROOT / "bifrost" / "apparmor.txt").read_text()
    assert text.startswith("#include <tunables/global>")
    assert "profile bifrost flags=(attach_disconnected,mediate_deleted)" in text
    for needed in ("file,", "capability,", "network inet,", "signal (receive) peer=unconfined,"):
        assert needed in text  # s6-overlay and Python must keep working
    assert text.count("{") == text.count("}") and "deny file" not in text
    assert "apparmor: false" not in (ROOT / "bifrost" / "config.yaml").read_text()
