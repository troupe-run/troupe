"""The changelog page links the changelogs release-please has written, names each part it hasn't
released yet, and copies none of them (spec: user-docs; user-docs design D4, changelog-links-exist
design)."""

import json
import re
from collections.abc import Callable
from pathlib import Path

import pytest

pytestmark = pytest.mark.docs  # reads docs/ (scripts/check-paths.toml)

ROOT = Path(__file__).resolve().parents[3]
PAGE = "docs/backstage/changelog.md"
CONFIG = "release-please-config.json"
LINK = re.compile(r"\]\(https://github\.com/troupe-run/troupe/blob/main/([^)#\s]+/CHANGELOG\.md)\)")
# A part not released yet: a list item that starts with its component in code
# (changelog-links-exist design D1).
LISTED = re.compile(r"^[ \t]*[-*+][ \t]+`([^`]+)`", re.MULTILINE)


def _changelog(path: str, package: dict[str, object]) -> str:
    return f"{path}/{package.get('changelog-path', 'CHANGELOG.md')}".removeprefix("./")


def written(config: str) -> set[str]:
    """Every changelog release-please writes: each package's own, unless it names another path."""
    packages = json.loads(config)["packages"]
    return {_changelog(path, package) for path, package in packages.items()}


def problems(page: str, config: str, exists: Callable[[str], bool]) -> list[str]:
    """What's wrong with the page, given the config and whether each changelog path exists yet."""
    packages: dict[str, dict[str, object]] = json.loads(config)["packages"]
    expected = written(config)
    linked = set(LINK.findall(page))
    listed = set(LISTED.findall(page))
    found = [
        f"{CONFIG}: {path} sets no component, which names the part on {PAGE}"
        for path, package in sorted(packages.items())
        if not isinstance(package.get("component"), str)
    ]
    if found:
        return found
    component = {
        _changelog(path, package): str(package["component"]) for path, package in packages.items()
    }
    found += [
        f"{PAGE} links {path}, which release-please doesn't write; it writes "
        f"{', '.join(sorted(expected))}"
        for path in sorted(linked - expected)
    ]
    found += [
        f"{PAGE} links {path}, which doesn't exist until {component[path]}'s first release: "
        f"until then, name it as - `{component[path]}`"
        for path in sorted(linked & expected)
        if not exists(path)
    ]
    # A listed part whose changelog exists passes: its first release pull request can't be edited
    # to link it (changelog-links-exist design D3).
    found += [
        f"{PAGE} doesn't link {path}, which release-please writes: link it, or, before "
        f"{component[path]}'s first release, name it as - `{component[path]}`"
        for path in sorted(expected - linked)
        if component[path] not in listed
    ]
    return found


def _exists(path: str) -> bool:
    return (ROOT / path).is_file()


def test_the_page_links_each_written_changelog_that_exists_or_lists_its_part() -> None:
    page = (ROOT / PAGE).read_text(encoding="utf-8")
    assert problems(page, (ROOT / CONFIG).read_text(encoding="utf-8"), _exists) == []


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


def _all_exist(path: str) -> bool:
    return True


def test_a_misnamed_changelog_is_named_with_the_changelogs_release_please_writes() -> None:
    page = (
        "[troupe](https://github.com/troupe-run/troupe/blob/main/packages/troupe/CHANGES.md)\n"
        "[protocol](https://github.com/troupe-run/troupe/blob/main/protocol/CHANGELOG.md)\n"
    )
    assert problems(page, CONFIG_SAMPLE, _all_exist) == [
        f"{PAGE} doesn't link packages/troupe/CHANGELOG.md, which release-please writes: link it, "
        "or, before troupe's first release, name it as - `troupe`"
    ]
    page = page.replace("CHANGES.md", "CHANGELOG.md").replace(
        "protocol/CHANGELOG", "protocol/CHANGES/CHANGELOG"
    )
    assert problems(page, CONFIG_SAMPLE, _all_exist) == [
        f"{PAGE} links protocol/CHANGES/CHANGELOG.md, which release-please doesn't write; it "
        "writes packages/troupe/CHANGELOG.md, protocol/CHANGELOG.md",
        f"{PAGE} doesn't link protocol/CHANGELOG.md, which release-please writes: link it, "
        "or, before protocol's first release, name it as - `protocol`",
    ]


def test_a_package_that_names_its_own_changelog_path_is_followed() -> None:
    config = json.dumps({"packages": {"protocol": {"changelog-path": "HISTORY.md"}}})
    assert written(config) == {"protocol/HISTORY.md"}


RUNNER_CONFIG = json.dumps(
    {"packages": {"plugins/runner-ollama": {"component": "troupe-runner-ollama"}}}
)
RUNNER_LINK = (
    "- [troupe-runner-ollama]"
    "(https://github.com/troupe-run/troupe/blob/main/plugins/runner-ollama/CHANGELOG.md)\n"
)


def test_a_link_to_a_changelog_not_written_yet_says_to_name_the_part() -> None:
    assert problems(RUNNER_LINK, RUNNER_CONFIG, set().__contains__) == [
        f"{PAGE} links plugins/runner-ollama/CHANGELOG.md, which doesn't exist until "
        "troupe-runner-ollama's first release: until then, name it as - `troupe-runner-ollama`"
    ]


def test_a_part_listed_by_name_with_no_changelog_passes() -> None:
    assert problems("- `troupe-runner-ollama`\n", RUNNER_CONFIG, set().__contains__) == []


def test_a_part_listed_by_name_whose_changelog_now_exists_passes() -> None:
    # A first release pull request writes the changelog, and only the release App may commit to it,
    # so the page links the changelog after the release merges (changelog-links-exist design D3).
    exists = {"plugins/runner-ollama/CHANGELOG.md"}.__contains__
    assert problems("- `troupe-runner-ollama`\n", RUNNER_CONFIG, exists) == []


def test_a_part_neither_linked_nor_listed_names_both_fixes() -> None:
    assert problems("", RUNNER_CONFIG, set().__contains__) == [
        f"{PAGE} doesn't link plugins/runner-ollama/CHANGELOG.md, which release-please writes: "
        "link it, or, before troupe-runner-ollama's first release, name it as "
        "- `troupe-runner-ollama`"
    ]


def test_a_part_named_in_prose_but_not_listed_counts_as_left_off() -> None:
    page = "The `troupe-runner-ollama` changelog starts with its first release.\n"
    assert len(problems(page, RUNNER_CONFIG, set().__contains__)) == 1


def test_a_package_with_no_component_is_named() -> None:
    config = json.dumps({"packages": {"plugins/runner-ollama": {}}})
    assert problems("", config, set().__contains__) == [
        f"{CONFIG}: plugins/runner-ollama sets no component, which names the part on {PAGE}"
    ]
