"""The changelog page links the changelogs release-please writes, and copies none of them (spec:
user-docs; user-docs design D4)."""

import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.docs  # reads docs/ (scripts/check-paths.toml)

ROOT = Path(__file__).resolve().parents[3]
PAGE = "docs/backstage/changelog.md"
CONFIG = "release-please-config.json"
LINK = re.compile(r"\]\(https://github\.com/troupe-run/troupe/blob/main/([^)#\s]+/CHANGELOG\.md)\)")


def written(config: str) -> set[str]:
    """Every changelog release-please writes: each package's own, unless it names another path."""
    packages = json.loads(config)["packages"]
    return {
        f"{path}/{package.get('changelog-path', 'CHANGELOG.md')}".removeprefix("./")
        for path, package in packages.items()
    }


def problems(page: str, config: str) -> list[str]:
    linked = set(LINK.findall(page))
    expected = written(config)
    found = [
        f"{PAGE} links {path}, which release-please doesn't write; it writes "
        f"{', '.join(sorted(expected))}"
        for path in sorted(linked - expected)
    ]
    found += [
        f"{PAGE} doesn't link {path}, which release-please writes"
        for path in sorted(expected - linked)
    ]
    return found


def test_the_page_links_exactly_the_changelogs_release_please_writes() -> None:
    page = (ROOT / PAGE).read_text(encoding="utf-8")
    assert problems(page, (ROOT / CONFIG).read_text(encoding="utf-8")) == []


def test_the_page_copies_no_changelog_entries() -> None:
    page = (ROOT / PAGE).read_text(encoding="utf-8")
    # release-please writes each version as a heading with its version and date.
    assert not re.search(r"^#+ \[?\d+\.\d+\.\d+", page, re.MULTILINE)


CONFIG_SAMPLE = json.dumps(
    {
        "packages": {
            "packages/troupe": {"component": "troupe"},
            "protocol": {"component": "protocol"},
        }
    }
)


def test_a_misnamed_changelog_is_named_with_the_changelogs_release_please_writes() -> None:
    page = (
        "[troupe](https://github.com/troupe-run/troupe/blob/main/packages/troupe/CHANGES.md)\n"
        "[protocol](https://github.com/troupe-run/troupe/blob/main/protocol/CHANGELOG.md)\n"
    )
    assert problems(page, CONFIG_SAMPLE) == [
        f"{PAGE} doesn't link packages/troupe/CHANGELOG.md, which release-please writes"
    ]
    page = page.replace("CHANGES.md", "CHANGELOG.md").replace(
        "protocol/CHANGELOG", "protocol/CHANGES/CHANGELOG"
    )
    assert problems(page, CONFIG_SAMPLE) == [
        f"{PAGE} links protocol/CHANGES/CHANGELOG.md, which release-please doesn't write; it "
        "writes packages/troupe/CHANGELOG.md, protocol/CHANGELOG.md",
        f"{PAGE} doesn't link protocol/CHANGELOG.md, which release-please writes",
    ]


def test_a_package_that_names_its_own_changelog_path_is_followed() -> None:
    config = json.dumps({"packages": {"protocol": {"changelog-path": "HISTORY.md"}}})
    assert written(config) == {"protocol/HISTORY.md"}
