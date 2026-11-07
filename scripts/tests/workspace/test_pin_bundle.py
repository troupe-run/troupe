"""The pinning step moves the bundle's pins to each component's latest release (spec: releases;
release-each-package design D4, D5).

Each case runs on a copy of the real files, with the manifest and changelogs set as a release would
leave them, and checks the files byte for byte."""

import json
import shutil
from pathlib import Path

import bundle_state
import pytest
from conftest import REPO

import pin_bundle
import release_config
from release_config import CONFIG, MANIFEST

FIRST = """# Changelog

## 0.1.0 (2026-10-31)


### ⚠ BREAKING CHANGES

* **runners:** the runner contract is version 0, the draft

### Features

* **vcs:** read branch, HEAD and what is committed through a VCS port ([4729252](https://github.com/troupe-run/troupe/commit/4729252))


### Bug Fixes

* **vcs:** mark a path that holds only its base stage resolved ([0b69d7c](https://github.com/troupe-run/troupe/commit/0b69d7c))
"""
"""A first release as release-please writes it (#89's troupe-vcs-git changelog, shortened)."""


def section(version: str, previous: str, component: str, *headings: str) -> str:
    """A later release's section, with release-please's compare-link heading."""
    body = "".join(f"\n\n### {heading}\n\n* **x:** something\n" for heading in headings)
    return (
        f"## [{version}](https://github.com/troupe-run/troupe/compare/{component}-v{previous}..."
        f"{component}-v{version}) (2026-11-02)\n{body}\n"
    )


def changelog(component: str, *sections: str) -> str:
    """FIRST under its title, with later sections above it, newest first."""
    return FIRST.replace("# Changelog\n\n", "# Changelog\n\n" + "".join(sections), 1)


@pytest.fixture
def copy(tmp_path: Path) -> Path:
    """The files the step reads and writes, copied from the repository, with every member at
    0.1.0 and a first-release changelog each, and the bundle unpinned, as merging the first
    release pull request leaves them, whatever state the repository is in (#229)."""
    for name in ("pyproject.toml", CONFIG, MANIFEST):
        shutil.copy(REPO / name, tmp_path / name)
    for path, name in release_config.members(REPO).items():
        (tmp_path / path).mkdir(parents=True)
        shutil.copy(REPO / path / "pyproject.toml", tmp_path / path / "pyproject.toml")
        (tmp_path / path / "CHANGELOG.md").write_bytes(changelog(name).encode())
    manifest = json.loads((tmp_path / MANIFEST).read_text(encoding="utf-8"))
    bundle = bundle_path(tmp_path)
    for path in manifest:
        manifest[path] = "0.0.0" if path == bundle else "0.1.0"
    (tmp_path / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    bundle_state.unpinned(tmp_path)
    return tmp_path


def bundle_path(root: Path) -> str:
    path = release_config.bundle_member(root)
    assert path is not None
    return path


def bundle_pyproject(root: Path) -> Path:
    return root / bundle_path(root) / "pyproject.toml"


def path_of(root: Path, name: str) -> str:
    [path] = [path for path, member in release_config.members(root).items() if member == name]
    return path


def release(root: Path, name: str, version: str, *headings: str) -> None:
    """Leave root as merging a release of name at version would: the manifest and changelog."""
    path = path_of(root, name)
    manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    previous = manifest[path]
    manifest[path] = version
    (root / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    log = root / path / "CHANGELOG.md"
    text = log.read_bytes().decode()
    log.write_bytes(
        text.replace(
            "# Changelog\n\n", "# Changelog\n\n" + section(version, previous, name, *headings), 1
        ).encode()
    )


def pin_all(root: Path) -> None:
    """Run the step once and keep its result: every member that has released pinned, and the
    exclusion gone if that leaves nothing bare."""
    pin_bundle.apply(root, pin_bundle.moves(root))


def run(root: Path, tmp_path: Path) -> tuple[int, str | None]:
    message = tmp_path / "message.txt"
    code = pin_bundle.main(["--root", str(root), "--message", str(message)])
    return code, message.read_text(encoding="utf-8") if message.exists() else None


def test_nothing_moves_when_every_pin_is_current(copy: Path, tmp_path: Path) -> None:
    pin_all(copy)
    before = {p: p.read_bytes() for p in (bundle_pyproject(copy), copy / CONFIG)}
    assert run(copy, tmp_path) == (0, None)
    assert {p: p.read_bytes() for p in before} == before


def test_the_first_pin_pins_every_member_and_changes_nothing_else(copy: Path) -> None:
    pyproject = bundle_pyproject(copy)
    before = pyproject.read_bytes().decode()
    moved = pin_bundle.moves(copy)
    others = {name for name in release_config.members(copy).values() if name != "troupe-run"}
    assert {move.name for move in moved} == others
    pin_bundle.apply(copy, moved)
    expected = before
    for path, name in release_config.members(copy).items():
        if name != "troupe-run":
            expected = expected.replace(
                f'"{name}"', f'"{release_config.pin(name, "0.1.0", path)}"', 1
            )
    assert expected != before
    assert pyproject.read_bytes().decode() == expected


def test_crlf_line_endings_are_kept(copy: Path) -> None:
    pyproject = bundle_pyproject(copy)
    pyproject.write_bytes(pyproject.read_bytes().replace(b"\n", b"\r\n"))
    before = pyproject.read_bytes()
    pin_bundle.apply(copy, pin_bundle.moves(copy))
    written = pyproject.read_bytes()
    assert written != before
    assert written.count(b"\r\n") == written.count(b"\n")


def test_the_first_pin_with_every_member_released_removes_only_the_exclusion(copy: Path) -> None:
    """The copy gives every member a release, so the first pin leaves nothing bare."""
    config = copy / CONFIG
    before = config.read_bytes().decode()
    line = f'      "exclude-paths": ["{bundle_path(copy)}"],\n'
    assert before.count(line) == 1
    pin_bundle.apply(copy, pin_bundle.moves(copy))
    assert config.read_bytes().decode() == before.replace(line, "")


def test_the_bundle_and_the_protocol_are_never_pinned(copy: Path) -> None:
    names = {move.name for move in pin_bundle.moves(copy)}
    assert "troupe-run" not in names
    assert "protocol" not in names
    assert names == {n for n in release_config.members(copy).values() if n != "troupe-run"}


def test_only_the_pin_behind_moves(copy: Path) -> None:
    pin_all(copy)
    release(copy, "troupe-vcs-git", "0.1.1", "Bug Fixes")
    [move] = pin_bundle.moves(copy)
    assert (move.name, move.old, move.new) == ("troupe-vcs-git", "0.1.0", "0.1.1")
    pin_bundle.apply(copy, [move])
    text = bundle_pyproject(copy).read_text(encoding="utf-8")
    assert release_config.pin("troupe-vcs-git", "0.1.1", "packages/troupe-vcs-git") in text
    assert release_config.pin("troupe-vcs-files", "0.1.0", "packages/troupe-vcs-files") in text


def test_only_fixes_make_a_fix(copy: Path) -> None:
    pin_all(copy)
    release(copy, "troupe-vcs-git", "0.1.1", "Bug Fixes")
    assert pin_bundle.kind(copy, pin_bundle.moves(copy)) == ("fix", [])


def test_a_feature_anywhere_makes_a_feat(copy: Path) -> None:
    """The spec's scenario: a fix in one adapter, a feature in another."""
    pin_all(copy)
    release(copy, "troupe-vcs-git", "0.1.1", "Bug Fixes")
    release(copy, "troupe-store-text", "0.2.0", "Features", "Bug Fixes")
    assert pin_bundle.kind(copy, pin_bundle.moves(copy)) == ("feat", [])


def test_a_breaking_change_is_named_with_its_version(copy: Path) -> None:
    pin_all(copy)
    release(copy, "troupe", "0.2.0", "⚠ BREAKING CHANGES", "Bug Fixes")
    assert pin_bundle.kind(copy, pin_bundle.moves(copy)) == ("fix", [("troupe", "0.2.0")])


def test_every_section_above_the_old_pin_counts(copy: Path) -> None:
    """Two releases since the last pin: a feature in the first counts as much as the second."""
    pin_all(copy)
    release(copy, "troupe-vcs-git", "0.2.0", "Features")
    release(copy, "troupe-vcs-git", "0.2.1", "Bug Fixes")
    assert pin_bundle.kind(copy, pin_bundle.moves(copy)) == ("feat", [])


def test_sections_at_or_below_the_old_pin_dont_count(copy: Path) -> None:
    """0.1.0's breaking changes were already shipped by the pin at 0.1.0."""
    pin_all(copy)
    release(copy, "troupe-vcs-git", "0.1.1", "Bug Fixes")
    assert pin_bundle.kind(copy, pin_bundle.moves(copy))[1] == []


def test_the_first_pin_counts_the_first_release(copy: Path) -> None:
    kind, breaking = pin_bundle.kind(copy, pin_bundle.moves(copy))
    assert kind == "feat"
    assert ("troupe", "0.1.0") in breaking


def test_one_move_names_it_in_the_subject(copy: Path, tmp_path: Path) -> None:
    pin_all(copy)
    release(copy, "troupe-vcs-git", "0.1.1", "Bug Fixes")
    code, message = run(copy, tmp_path)
    assert code == 0
    assert message is not None
    subject, _, rest = message.partition("\n")
    assert subject == "fix(bundle): ship troupe-vcs-git 0.1.1"
    assert "- troupe-vcs-git: 0.1.0 → 0.1.1" in rest
    signoff = json.loads((copy / CONFIG).read_text(encoding="utf-8"))["signoff"]
    assert message.endswith(f"\n\nSigned-off-by: {signoff}\n")


def test_a_breaking_message_marks_the_subject_and_names_each_in_the_footer(
    copy: Path, tmp_path: Path
) -> None:
    pin_all(copy)
    release(copy, "troupe", "0.2.0", "⚠ BREAKING CHANGES")
    release(copy, "troupe-vcs-git", "0.2.0", "⚠ BREAKING CHANGES", "Features")
    _, message = run(copy, tmp_path)
    assert message is not None
    subject = message.partition("\n")[0]
    assert subject == "feat(bundle)!: ship troupe 0.2.0, troupe-vcs-git 0.2.0"
    assert (
        "BREAKING CHANGE: troupe 0.2.0 and troupe-vcs-git 0.2.0 have breaking changes: see "
        "packages/troupe/CHANGELOG.md and packages/troupe-vcs-git/CHANGELOG.md."
    ) in message


def test_the_first_pins_subject_fits_in_72_characters(copy: Path, tmp_path: Path) -> None:
    _, message = run(copy, tmp_path)
    assert message is not None
    subject = message.partition("\n")[0]
    count = len(release_config.members(copy)) - 1
    assert subject == f"feat(bundle)!: ship {count} component releases"
    assert len(subject) <= 72


def test_a_pin_above_the_manifest_stops_naming_the_file(copy: Path) -> None:
    pin_all(copy)
    pyproject = bundle_pyproject(copy)
    old = release_config.pin("troupe-vcs-git", "0.1.0", "packages/troupe-vcs-git")
    new = release_config.pin("troupe-vcs-git", "0.3.0", "packages/troupe-vcs-git")
    pyproject.write_bytes(pyproject.read_bytes().replace(old.encode(), new.encode()))
    with pytest.raises(pin_bundle.PinError, match=r"pins troupe-vcs-git at 0\.3\.0.*0\.1\.0"):
        pin_bundle.moves(copy)


def test_a_malformed_pin_stops_naming_the_file(copy: Path) -> None:
    pyproject = bundle_pyproject(copy)
    pyproject.write_bytes(
        pyproject.read_bytes().replace(b'"troupe-vcs-git"', b'"troupe-vcs-git>=0.1"')
    )
    with pytest.raises(pin_bundle.PinError, match=r"pyproject\.toml is 'troupe-vcs-git>=0\.1'"):
        pin_bundle.moves(copy)


def test_a_changelog_without_the_new_version_stops_naming_it(copy: Path) -> None:
    pin_all(copy)
    path = path_of(copy, "troupe-vcs-git")
    manifest = json.loads((copy / MANIFEST).read_text(encoding="utf-8"))
    manifest[path] = "0.1.1"
    (copy / MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(pin_bundle.PinError, match=rf"{path}/CHANGELOG\.md has no 0\.1\.1"):
        pin_bundle.kind(copy, pin_bundle.moves(copy))


def test_a_failure_exits_1_and_writes_nothing(
    copy: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (copy / path_of(copy, "troupe") / "CHANGELOG.md").unlink()
    before = bundle_pyproject(copy).read_bytes()
    assert run(copy, tmp_path) == (1, None)
    assert bundle_pyproject(copy).read_bytes() == before
    assert "CHANGELOG.md" in capsys.readouterr().err


def test_the_result_passes_the_release_configuration_check(copy: Path) -> None:
    """After the first pin and the bundle's release, the check finds nothing wrong."""
    shutil.copy(REPO / "uv.lock", copy / "uv.lock")
    record = release_config.PROTOCOL_RECORD
    (copy / record).parent.mkdir(parents=True)
    shutil.copy(REPO / record, copy / record)
    manifest = json.loads((copy / MANIFEST).read_text(encoding="utf-8"))
    (copy / record).write_text(json.dumps({"version": manifest["protocol"]}), encoding="utf-8")
    pin_bundle.apply(copy, pin_bundle.moves(copy))
    assert release_config.problems(copy) == []
    manifest[bundle_path(copy)] = "0.1.0"
    (copy / MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    assert release_config.problems(copy) == []


STILL_BARE = (
    "troupe-example is still bare, so troupe-run doesn't release until a pinning pull request "
    "pins it, after its first release (refuse-bare-bundle-member design D3)."
)


def checkable(root: Path) -> None:
    """Give the copy what release_config.problems also reads: uv.lock and the protocol record."""
    shutil.copy(REPO / "uv.lock", root / "uv.lock")
    record = release_config.PROTOCOL_RECORD
    (root / record).parent.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    (root / record).write_text(json.dumps({"version": manifest["protocol"]}), encoding="utf-8")


def with_a_new_member(root: Path) -> None:
    """After the bundle's first pin and release, troupe-example added bare with the exclusion,
    as the check requires (spec: releases)."""
    checkable(root)
    pin_all(root)
    manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    manifest[bundle_path(root)] = "0.1.0"
    (root / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    bundle_state.add_member(root, "troupe-example")
    bundle_state.exclude(root)
    assert release_config.problems(root) == []


def test_a_pin_that_leaves_a_member_bare_keeps_the_exclusion_and_says_so(
    copy: Path, tmp_path: Path
) -> None:
    with_a_new_member(copy)
    config = copy / CONFIG
    before = config.read_bytes()
    release(copy, "troupe", "0.2.0", "Features")
    code, text = run(copy, tmp_path)
    assert code == 0
    assert config.read_bytes() == before
    assert text is not None
    assert STILL_BARE in text
    assert release_config.problems(copy) == []


def test_pinning_the_last_bare_member_removes_the_exclusion_and_says_nothing_of_it(
    copy: Path, tmp_path: Path
) -> None:
    with_a_new_member(copy)
    config = copy / CONFIG
    line = f'      "exclude-paths": ["{bundle_path(copy)}"],\n'
    before = config.read_bytes().decode()
    assert before.count(line) == 1
    path = path_of(copy, "troupe-example")
    (copy / path / "CHANGELOG.md").write_bytes(changelog("troupe-example").encode())
    manifest = json.loads((copy / MANIFEST).read_text(encoding="utf-8"))
    manifest[path] = "0.1.0"
    (copy / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    code, text = run(copy, tmp_path)
    assert code == 0
    assert config.read_bytes().decode() == before.replace(line, "")
    assert text is not None
    assert "still bare" not in text
    assert release_config.problems(copy) == []


def test_a_release_of_a_runner_in_an_extra_moves_its_pin_in_the_extra_and_in_all(
    copy: Path,
) -> None:
    """releases: "A runner in an extra released" (runner-extras design D3)."""
    bundle_state.copy_runner_table(REPO, copy)
    name = bundle_state.add_runner(copy, "lm-studio", extra="lm-studio")
    path = path_of(copy, name)
    (copy / path / "CHANGELOG.md").write_bytes(changelog(name).encode())
    release(copy, name, "0.1.0")
    pin_all(copy)
    before = bundle_pyproject(copy).read_bytes()
    release(copy, name, "0.1.1", "Bug Fixes")
    moved = pin_bundle.moves(copy)
    assert [(m.name, m.old, m.new) for m in moved] == [(name, "0.1.0", "0.1.1")]
    pin_bundle.apply(copy, moved)
    after = bundle_pyproject(copy).read_bytes()
    old = release_config.pin(name, "0.1.0", path)
    new = release_config.pin(name, "0.1.1", path)
    assert bundle_state.extras(copy)["lm-studio"] == [new]
    assert bundle_state.extras(copy)["all"] == [new]
    assert after == before.replace(old.encode(), new.encode())
