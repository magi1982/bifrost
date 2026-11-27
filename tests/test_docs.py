"""Home Assistant shows the changelog from the app folder – keep it identical to the repository one."""

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_app_changelog_matches_repository_changelog():
    assert (ROOT / "bifrost" / "CHANGELOG.md").read_text() == (ROOT / "CHANGELOG.md").read_text()


def test_changelog_has_entry_for_current_version():
    version = re.search(r'^version: "([^"]+)"', (ROOT / "bifrost" / "config.yaml").read_text(), re.M).group(1)
    assert f"## [{version}]" in (ROOT / "CHANGELOG.md").read_text()
