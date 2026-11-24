"""What test_release_notes.py and test_release_notes_integration.py share."""

import json
import re
from pathlib import Path

import release_notes
from release_config import CONFIG, MANIFEST
from release_tags import expected

WARNING = "### ⚠ BREAKING CHANGES"

SECTION = """## [0.2.0](https://example.invalid/compare/v0.1.0...v0.2.0) (2026-11-19)


### ⚠ BREAKING CHANGES

* **api:** the old call is gone

### Features

* **api:** a new call ([abc1234](https://example.invalid/commit/abc1234))
"""
OLDER = """## 0.1.0 (2026-11-01)


### Features

* **api:** the first call ([def5678](https://example.invalid/commit/def5678))
"""


def write_root(
    tmp_path: Path,
    versions: dict[str, str] | None = None,
    changelogs: dict[str, str | None] | None = None,
) -> Path:
    """A root whose config names components `example` and `other` at pkgs/<name>, with a manifest
    and a changelog for each. A changelog given as None isn't written."""
    versions = versions or {"example": "0.2.0", "other": "0.1.0"}
    texts: dict[str, str | None] = {
        "example": f"# Changelog\n\n{SECTION}\n{OLDER}",
        "other": f"# Changelog\n\n{OLDER}",
    }
    texts |= changelogs or {}
    config = {
        "include-component-in-tag": True,
        "packages": {f"pkgs/{name}": {"component": name} for name in versions},
    }
    (tmp_path / CONFIG).write_text(json.dumps(config), encoding="utf-8")
    manifest = {f"pkgs/{name}": version for name, version in versions.items()}
    (tmp_path / MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    for name in versions:
        text = texts.get(name)
        if text is not None:
            (tmp_path / "pkgs" / name).mkdir(parents=True)
            (tmp_path / "pkgs" / name / "CHANGELOG.md").write_bytes(text.encode("utf-8"))
    return tmp_path


def line(tag: str, body: str | None, draft: bool = False) -> str:
    """One release as the workflow's `gh api ... --jq '... | @json'` prints it."""
    return json.dumps([tag, body, draft], ensure_ascii=False)


def redated(notes: str) -> str:
    """The notes with the heading's date moved, as when a release merges after it was written."""
    return re.sub(r"\(\d{4}-\d\d-\d\d\)", "(2026-12-31)", notes, count=1)


def good(root: Path) -> list[str]:
    return [line(tag, redated(release_notes.section(root, tag))) for tag in expected(root)]
