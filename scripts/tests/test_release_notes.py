"""Every recorded version's release notes match its changelog section, apart from the heading's
date, and a release whose notes differ fails the release run, naming it (spec: releases;
release-notes-non-ascii design D1 to D7).

Most tests use a scratch root with one or two made-up components, so each scenario's input is
written out. The reproduction tests read the real 0.2.0 artefacts: eeab95c's release-notes.md blob
as git held it, the six releases as published, and this checkout's changelogs, whose 0.2.0-era
sections never change."""

import hashlib
import html
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import REPO, SCRIPTS

import release_notes
from release_config import CONFIG, MANIFEST
from release_tags import UnreadableError, expected

FIXTURES = Path(__file__).parent / "fixtures" / "release-notes"
BEFORE = FIXTURES / "release-notes-eeab95c-before.md"
"""#263's notes as release-please 17.6.0 had them before saving: eeab95c's release-notes.md blob
with each lone 0xA0 put back as the ⚠ it was cut from (D7). Kept as text, which a review can read;
the tests rebuild the blob from it and check its git id."""
BLOB_ID = "055e5de4f6ab666da7ab26877b329446a5305560"
"""The git id of eeab95c's release-notes.md blob: the `sha` the contents API gives for
`repos/troupe-run/troupe/contents/release-notes.md?ref=eeab95c`."""
PUBLISHED = sorted(path for path in FIXTURES.glob("*.md") if path != BEFORE)
"""The six releases #486 names, their bodies as published (fetched 2026-11-24)."""
LOST = {path.stem for path in PUBLISHED}
WARNING = "### ⚠ BREAKING CHANGES"
SKIPPED_IN_0_2_0 = {"troupe-runner-ollama-v0.1.0", "protocol-v0.2.0"}
"""The two components #263's run didn't release (#484); released later from an inline body."""

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


def test_notes_equal_to_their_sections_apart_from_the_date_pass(tmp_path: Path) -> None:
    root = write_root(tmp_path)
    assert release_notes.check(root, good(root)) == ([], [])


def test_releases_built_from_this_repositorys_changelogs_pass() -> None:
    assert release_notes.check(REPO, good(REPO)) == ([], [])


def test_notes_that_lost_their_warning_sign_name_the_release_line_and_replacements(
    tmp_path: Path,
) -> None:
    root = write_root(tmp_path)
    lines = good(root)
    lines[0] = line("example-v0.2.0", SECTION.replace("⚠", "�"))
    unreleased, [difference] = release_notes.check(root, lines)
    assert unreleased == []
    assert difference == release_notes.Difference(
        tag="example-v0.2.0",
        line=4,
        changelog=WARNING,
        notes="### � BREAKING CHANGES",
        replacements=1,
    )
    report = release_notes.report(unreleased, [difference])
    assert "example-v0.2.0's notes differ from its changelog section at line 4" in report
    assert "1 U+FFFD" in report
    assert release_notes.REPAIR in report


def test_notes_that_swallowed_another_components_block_fail(tmp_path: Path) -> None:
    root = write_root(tmp_path)
    lines = good(root)
    lines[0] = line("example-v0.2.0", SECTION + "\n" + OLDER)
    _, [difference] = release_notes.check(root, lines)
    assert difference.tag == "example-v0.2.0"
    assert difference.changelog == "(end of section)"
    assert difference.replacements == 0
    assert "U+FFFD" not in release_notes.report([], [difference])


def test_a_date_anywhere_but_the_heading_still_counts(tmp_path: Path) -> None:
    root = write_root(tmp_path)
    lines = good(root)
    lines[0] = line("example-v0.2.0", SECTION.replace("a new call", "a new call (2026-11-19)"))
    _, [difference] = release_notes.check(root, lines)
    assert difference.line == 10


def test_crlf_and_surrounding_whitespace_dont_count(tmp_path: Path) -> None:
    root = write_root(tmp_path)
    lines = good(root)
    lines[0] = line("example-v0.2.0", "\n" + SECTION.replace("\n", "\r\n") + "\r\n\r\n")
    assert release_notes.check(root, lines) == ([], [])


@pytest.mark.parametrize("draft", [False, True], ids=["absent", "draft only"])
def test_a_tag_with_no_published_release_has_no_notes_to_compare(
    tmp_path: Path, draft: bool
) -> None:
    root = write_root(tmp_path)
    lines = good(root)[1:] + ([line("example-v0.2.0", SECTION, draft=True)] if draft else [])
    unreleased, differences = release_notes.check(root, lines)
    assert (unreleased, differences) == (["example-v0.2.0"], [])
    assert "no notes to compare: example-v0.2.0." in release_notes.report(unreleased, differences)


def test_a_release_with_no_body_differs(tmp_path: Path) -> None:
    root = write_root(tmp_path)
    lines = good(root)
    lines[0] = line("example-v0.2.0", None)
    _, [difference] = release_notes.check(root, lines)
    assert difference.line == 1


def test_a_version_with_no_changelog_section_is_an_error_naming_both(tmp_path: Path) -> None:
    root = write_root(tmp_path, {"example": "0.3.0", "other": "0.1.0"})
    lines = [line("example-v0.3.0", SECTION), line("other-v0.1.0", OLDER)]
    with pytest.raises(
        UnreadableError, match=r"pkgs/example/CHANGELOG\.md has no section for 0\.3\.0"
    ):
        release_notes.check(root, lines)


def test_a_missing_changelog_is_an_error_naming_it(tmp_path: Path) -> None:
    root = write_root(tmp_path, changelogs={"other": None})
    with pytest.raises(UnreadableError, match=r"pkgs/other/CHANGELOG\.md doesn't exist"):
        release_notes.check(root, [line("example-v0.2.0", SECTION), line("other-v0.1.0", OLDER)])


def test_a_member_at_0_0_0_needs_no_release(tmp_path: Path) -> None:
    root = write_root(tmp_path, {"example": "0.2.0", "other": "0.0.0"}, {"other": "# Changelog\n"})
    assert release_notes.check(root, [line("example-v0.2.0", SECTION)]) == ([], [])


def test_releases_the_manifest_doesnt_name_are_ignored(tmp_path: Path) -> None:
    root = write_root(tmp_path)
    lines = [*good(root), line("example-v0.1.0", "anything"), line("gone-v9.9.9", "")]
    assert release_notes.check(root, lines) == ([], [])


@pytest.mark.parametrize(
    "bad",
    [
        "not json",
        '{"tag": "example-v0.2.0"}',
        '["example-v0.2.0", "notes"]',
        '["example-v0.2.0", 1, false]',
    ],
)
def test_an_input_line_that_isnt_a_tag_body_draft_array_is_an_error(
    tmp_path: Path, bad: str
) -> None:
    root = write_root(tmp_path)
    with pytest.raises(UnreadableError, match="input line 2"):
        release_notes.check(root, [good(root)[0], bad])


def test_a_tag_listed_twice_is_an_error(tmp_path: Path) -> None:
    root = write_root(tmp_path)
    lines = good(root)
    with pytest.raises(UnreadableError, match=r"lists 'example-v0\.2\.0' a second time"):
        release_notes.check(root, [*lines, lines[0]])


def test_a_section_runs_from_its_heading_to_the_next_level_two_heading(tmp_path: Path) -> None:
    root = write_root(tmp_path)
    assert release_notes.section(root, "example-v0.2.0") == SECTION
    assert release_notes.section(root, "example-v0.1.0") == OLDER


def test_a_tag_whose_component_isnt_configured_has_no_section(tmp_path: Path) -> None:
    root = write_root(tmp_path)
    with pytest.raises(UnreadableError, match=r"component 'gone' of tag 'gone-v0\.1\.0'"):
        release_notes.section(root, "gone-v0.1.0")


def run(root: Path, *args: str, stdin: str = "") -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "release_notes.py"), "--root", str(root), *args],
        input=stdin.encode("utf-8"),
        capture_output=True,
        check=False,
    )


def test_the_script_exits_0_when_every_release_matches(tmp_path: Path) -> None:
    root = write_root(tmp_path)
    result = run(root, stdin="\n".join(good(root)) + "\n")
    assert (result.returncode, result.stderr) == (0, b"")


def test_the_script_exits_1_naming_a_release_that_differs(tmp_path: Path) -> None:
    root = write_root(tmp_path)
    lines = good(root)
    lines[0] = line("example-v0.2.0", SECTION.replace("⚠", "�"))
    result = run(root, stdin="\n".join(lines))
    assert result.returncode == 1
    stderr = result.stderr.decode("utf-8")
    assert "example-v0.2.0's notes differ" in stderr
    assert f"changelog: {WARNING}" in stderr


def test_the_script_exits_1_naming_an_unreadable_input(tmp_path: Path) -> None:
    result = run(write_root(tmp_path), stdin="not json\n")
    assert result.returncode == 1
    assert result.stderr.decode("utf-8").startswith("release notes: input line 1 isn't JSON")


def test_the_script_prints_a_tags_section_for_its_repair(tmp_path: Path) -> None:
    result = run(write_root(tmp_path), "--section", "example-v0.2.0")
    assert (result.returncode, result.stdout.decode("utf-8")) == (0, SECTION)


def test_the_script_refuses_the_section_of_an_unconfigured_tag(tmp_path: Path) -> None:
    result = run(write_root(tmp_path), "--section", "gone-v0.1.0")
    assert (result.returncode, result.stdout) == (1, b"")
    assert "'gone-v0.1.0'" in result.stderr.decode("utf-8")


# The 0.2.0 reproduction (design D7).


def node_binary(text: str) -> bytes:
    """What Node's `Buffer.from(text, 'binary')` makes of text: each UTF-16 code unit's low byte.
    It's how release-please 17.6.0's createFileOnNewBranch encodes an overflowed body."""
    return text.encode("utf-16-le")[::2]


def blob() -> bytes:
    """What release-please saved: the notes encoded as createFileOnNewBranch encodes them."""
    return node_binary(BEFORE.read_bytes().decode("utf-8"))


def read_back() -> str:
    """The blob as release-please read it: git-file-utils decodes it as UTF-8, with replacement."""
    return blob().decode("utf-8", errors="replace")


def blocks() -> dict[str, str]:
    """Each component's notes in the read-back text, by tag. A plain split on release-please's
    `<details>` blocks, with entities decoded as its parser's textContent does: enough to feed the
    check, which is what's under test, not the parser."""
    found = re.findall(
        r"<details><summary>(?P<component>[^:<]+): (?P<version>[\d.]+)</summary>\n"
        r"(?P<notes>.*?)</details>",
        read_back(),
        flags=re.DOTALL,
    )
    return {f"{c}-v{v}": html.unescape(notes) for c, v, notes in found}


def test_encoding_the_notes_as_release_please_does_gives_eeab95cs_blob() -> None:
    saved = blob()
    assert (
        hashlib.sha1(b"blob %d\0" % len(saved) + saved, usedforsecurity=False).hexdigest()
        == BLOB_ID
    )


def test_the_blob_holds_the_low_byte_of_each_warning_sign_and_no_other_non_ascii() -> None:
    saved = blob()
    assert node_binary(WARNING) == b"### \xa0 BREAKING CHANGES"
    assert saved.count(node_binary(WARNING)) == 8
    assert sum(byte > 0x7F for byte in saved) == 8


def test_reading_the_blob_back_turns_each_warning_sign_into_a_replacement() -> None:
    text = read_back()
    assert text.count("### � BREAKING CHANGES") == 8
    assert all(ord(char) < 0x80 for char in text.replace("�", ""))


def test_the_check_names_exactly_the_releases_that_lost_text_in_0_2_0() -> None:
    notes = blocks()
    assert len(notes) == 13
    released = {tag: body for tag, body in notes.items() if tag not in SKIPPED_IN_0_2_0}
    differing = {
        tag
        for tag, body in released.items()
        if release_notes.compare(tag, release_notes.section(REPO, tag), body) is not None
    }
    assert differing == LOST


@pytest.mark.parametrize("published", PUBLISHED, ids=lambda path: path.stem)
def test_each_published_release_fails_and_its_changelog_section_passes(published: Path) -> None:
    tag = published.stem
    body = published.read_bytes().decode("utf-8")
    changelog = release_notes.section(REPO, tag)
    difference = release_notes.compare(tag, changelog, body)
    assert difference is not None
    assert (difference.changelog, difference.notes) == (WARNING, "### � BREAKING CHANGES")
    assert difference.replacements == body.count("�") >= 1
    assert release_notes.compare(tag, changelog, redated(changelog)) is None


def test_the_fixtures_hold_the_six_published_releases() -> None:
    assert len(LOST) == 6
