"""Config's files: the kinds of file, rendering them, the check before replacing one, staged writes
and flush (spec: config-files; config-model design D7, D8, D9)."""

import subprocess
import sys
import textwrap
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import jsonschema
import pytest
import yaml as yaml_1_1  # PyYAML reads YAML 1.1, as many editors do
from hypothesis import example, given
from hypothesis import strategies as st
from ruamel.yaml import YAML

from configtesting import TESTER
from gitrepo import make_repo
from protocol_schemas import PROTOCOL_BASE, SCRIPTED, check_error, check_notice, validator_for
from troupe.core import schemas
from troupe.core.config.kinds import file_kind, staged_name, staged_target
from troupe.core.config.projection import (
    WRITTEN,
    Action,
    Resolved,
    execute,
    file_hash,
    flush,
    locked,
    merge_notices,
    on_disk,
    plan,
    render,
    render_actor,
    stage,
)
from troupe.core.errors import TroupeError
from troupe.core.settings import Marking
from troupe.core.vcs import Marked, MergeSides, Resolve

ACTOR_FILE = validator_for(PROTOCOL_BASE + "config/actor.schema.json", SCRIPTED)
CONFIG: dict[str, Any] = {"actors": {"tester": TESTER}}


def _theatre(tmp_path: Path) -> Path:
    (tmp_path / ".troupe").mkdir()
    return tmp_path


def _actor_file(theatre: Path) -> Path:
    return theatre / ".troupe" / "actors" / "tester.yaml"


# Requirement: Files in config directories are known kinds


def test_an_actors_files_are_known_kinds_and_their_staged_writes_are_named_beside_them() -> None:
    assert file_kind("actors/tester.yaml") is not None
    assert file_kind("actors/tester.md") is not None
    assert file_kind("actors/Tester.yaml") is None
    assert file_kind("actors/notes.txt") is None
    assert staged_name("actors/tester.yaml") == "actors/.tester.yaml.troupe~"
    assert staged_target("actors/.tester.yaml.troupe~") == "actors/tester.yaml"
    assert staged_target("actors/tester.yaml") is None


def test_a_stray_file_in_a_config_directory_is_refused_naming_it(tmp_path: Path) -> None:
    theatre = _theatre(tmp_path)
    (theatre / ".troupe" / "actors").mkdir()
    (theatre / ".troupe" / "actors" / "notes.txt").write_text("mine", encoding="utf-8")
    with pytest.raises(TroupeError) as caught:
        flush(theatre, CONFIG, {})
    assert caught.value.code == "config.unknown-file"
    assert caught.value.details["paths"] == [".troupe/actors/notes.txt"]
    check_error(caught.value.to_data())
    assert not _actor_file(theatre).exists()  # refused before anything was written


def test_finders_metadata_is_ignored(tmp_path: Path) -> None:
    theatre = _theatre(tmp_path)
    (theatre / ".troupe" / "actors").mkdir()
    (theatre / ".troupe" / "actors" / ".DS_Store").write_bytes(b"\x00\x01")
    flush(theatre, CONFIG, {})
    assert on_disk(theatre / ".troupe").unknown == ()


# Requirement: Each actor is projected to its own files


def test_an_actor_is_written_to_its_yaml_file_and_its_character_to_its_md_file(
    tmp_path: Path,
) -> None:
    theatre = _theatre(tmp_path)
    flush(theatre, CONFIG, {})
    text = _actor_file(theatre).read_text(encoding="utf-8")
    assert "character" not in text
    assert (theatre / ".troupe" / "actors" / "tester.md").read_bytes() == b"You are the tester."


def test_an_actor_with_no_character_has_no_md_file() -> None:
    without = {key: value for key, value in TESTER.items() if key != "character"}
    assert set(render({"actors": {"tester": without}})) == {"actors/tester.yaml"}


def test_a_removed_actors_files_are_removed(tmp_path: Path) -> None:
    theatre = _theatre(tmp_path)
    flush(theatre, CONFIG, {})
    recorded = {path: frozenset({file_hash(data)}) for path, data in render(CONFIG).items()}
    flush(theatre, {}, recorded)
    assert not (theatre / ".troupe" / "actors").exists()


# Requirement: Each config file names its schema twice


def test_an_actor_file_names_its_schema_in_its_first_line_and_its_first_key() -> None:
    text = render_actor(TESTER)["yaml"].decode("utf-8")
    first, second, *_ = text.splitlines()
    url = "https://troupe.run/protocol/0/config/actor.schema.json"
    assert first == f"# yaml-language-server: $schema={url}"
    assert second == f"$schema: {url}"


def test_an_actor_file_names_its_schema_by_the_major_of_the_protocol_troupe_carries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = tmp_path / "version.json"
    record.write_bytes(b'{"version":"1.3.0"}\n')
    monkeypatch.setattr(schemas, "PROTOCOL_RECORD", record)
    text = render_actor(TESTER)["yaml"].decode("utf-8")
    first, second, *_ = text.splitlines()
    url = "https://troupe.run/protocol/1/config/actor.schema.json"
    assert first == f"# yaml-language-server: $schema={url}"
    assert second == f"$schema: {url}"


def test_the_keys_are_in_the_schemas_order() -> None:
    keys = [
        line.split(":")[0]
        for line in render_actor(TESTER)["yaml"].decode("utf-8").splitlines()
        if line and not line.startswith((" ", "#", "-"))
    ]
    assert keys == ["$schema", "runner", "options", "expect"]


def test_a_written_actor_file_validates_against_the_actor_schema() -> None:
    data = YAML(typ="safe", pure=True).load(render_actor(TESTER)["yaml"])
    ACTOR_FILE.validate(data)


SCALARS = st.one_of(
    st.text(max_size=12),
    st.sampled_from(["yes", "no", "on", "off", "~", "null", "1e3", "012", "1:20", "a: b", "- x"]),
    st.integers(),
    st.floats(allow_nan=False, allow_infinity=False),
    st.booleans(),
)
JSON = st.recursive(
    SCALARS,
    lambda inner: st.lists(inner, max_size=3) | st.dictionaries(st.text(max_size=5), inner),
    max_leaves=8,
)


@given(st.dictionaries(st.text(min_size=1, max_size=6), JSON, max_size=4))
@example({"\x85": []})  # NEL: a line break to YAML 1.1
@example({"0": 1e-05})  # a YAML 1.1 float needs a dot
@example({"yes": "no", "on": "~"})
def test_a_written_file_reads_back_the_same_under_yaml_1_2_and_yaml_1_1(
    options: dict[str, Any],
) -> None:
    actor = {"runner": "scripted", "options": options, "expect": []}
    data = render_actor(actor)["yaml"]
    expected = {"$schema": "https://troupe.run/protocol/0/config/actor.schema.json", **actor}
    assert YAML(typ="safe", pure=True).load(data) == expected
    assert yaml_1_1.safe_load(data) == expected


# Requirement: Only a file troupe wrote is replaced


def test_a_file_edited_by_hand_is_refused_naming_it_and_the_fix_and_nothing_is_written(
    tmp_path: Path,
) -> None:
    theatre = _theatre(tmp_path)
    flush(theatre, CONFIG, {})
    edited = _actor_file(theatre).read_text(encoding="utf-8").replace("scripted", "mine")
    _actor_file(theatre).write_text(edited, encoding="utf-8")
    changed = {"actors": {"tester": {**TESTER, "character": "New."}}}
    with pytest.raises(TroupeError) as caught:
        flush(theatre, changed, {})
    assert caught.value.code == "config.file-not-troupes"
    assert caught.value.details["paths"] == [".troupe/actors/tester.yaml"]
    assert "git restore" in caught.value.fix
    assert "troupe flush --force" in caught.value.fix
    check_error(caught.value.to_data())
    assert _actor_file(theatre).read_text(encoding="utf-8") == edited
    assert (theatre / ".troupe" / "actors" / "tester.md").read_text("utf-8") == TESTER["character"]


def test_an_older_version_troupe_recorded_is_written_again_with_a_notice(tmp_path: Path) -> None:
    theatre = _theatre(tmp_path)
    old = {"actors": {"tester": {**TESTER, "expect": []}}}
    flush(theatre, old, {})
    recorded = {path: frozenset({file_hash(data)}) for path, data in render(old).items()}
    flushed = flush(theatre, CONFIG, recorded)
    assert _actor_file(theatre).read_bytes() == render(CONFIG)["actors/tester.yaml"]
    [notice] = flushed.notices()
    assert notice.code == "config.file-rewritten"
    assert "an older version troupe wrote" in notice.problem
    check_notice(notice.to_data())


def test_a_version_flush_wrote_itself_counts_as_troupes(tmp_path: Path) -> None:
    theatre = _theatre(tmp_path)
    old = {"actors": {"tester": {**TESTER, "expect": []}}}
    flush(theatre, old, {})  # written with no event: only this clone's record vouches for it
    assert (theatre / ".troupe" / WRITTEN).is_file()
    flush(theatre, CONFIG, {})
    assert _actor_file(theatre).read_bytes() == render(CONFIG)["actors/tester.yaml"]


def test_a_deleted_file_is_written_again_with_a_notice_naming_it(tmp_path: Path) -> None:
    theatre = _theatre(tmp_path)
    flush(theatre, CONFIG, {})
    _actor_file(theatre).unlink()
    recorded = {path: frozenset({file_hash(data)}) for path, data in render(CONFIG).items()}
    flushed = flush(theatre, CONFIG, recorded)
    assert _actor_file(theatre).exists()
    [notice] = flushed.notices()
    assert notice.path == ".troupe/actors/tester.yaml"


def test_nothing_to_do_changes_nothing(tmp_path: Path) -> None:
    theatre = _theatre(tmp_path)
    flush(theatre, CONFIG, {})
    before = _actor_file(theatre).stat().st_mtime_ns
    assert flush(theatre, CONFIG, {}).actions == ()
    assert _actor_file(theatre).stat().st_mtime_ns == before


def test_a_clean_git_merge_of_two_branches_files_is_left_as_it_is(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    theatre = repo.path
    flush(theatre, CONFIG, {})
    repo.commit_all("tester")
    repo.git("switch", "-q", "-c", "feature")
    runner_changed = {"actors": {"tester": {**TESTER, "expect": ["out/other.txt"]}}}
    flush(theatre, runner_changed, {})
    repo.commit_all("expect")
    repo.git("switch", "-q", "main")
    character_changed = {"actors": {"tester": {**TESTER, "character": "Changed on main."}}}
    flush(theatre, character_changed, {})
    repo.commit_all("character")
    repo.git("merge", "-q", "--no-edit", "feature")
    merged = {
        "actors": {
            "tester": {**TESTER, "expect": ["out/other.txt"], "character": "Changed on main."}
        }
    }
    assert flush(theatre, merged, {}).actions == ()


def test_conflict_markers_typed_by_hand_outside_any_merge_are_refused_and_left_alone(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    theatre = repo.path
    flush(theatre, CONFIG, {})
    repo.commit_all("tester")
    marked = b"<<<<<<< mine\nrunner: a\n=======\nrunner: b\n>>>>>>> theirs\n"
    _actor_file(theatre).write_bytes(marked)
    with pytest.raises(TroupeError) as caught:
        flush(theatre, CONFIG, {})
    assert caught.value.code == "config.file-not-troupes"
    assert "conflict markers" in caught.value.problem
    assert _actor_file(theatre).read_bytes() == marked


# Requirement: A file git merged from troupe's versions is rewritten from the merged config, and
# Only an explicit command rewrites a file git merged (config-projection-conflicts design D4, D5).
# These drive the plan with the merge sides a VCS would report; the git adapter's own tests show
# it reports them.

YAML_FILE = "actors/tester.yaml"
MD_FILE = "actors/tester.md"
OURS: dict[str, Any] = {"actors": {"tester": {**TESTER, "expect": ["out/ours.txt"]}}}
THEIRS: dict[str, Any] = {"actors": {"tester": {**TESTER, "runner": "theirs"}}}
MERGED_CONFIG: dict[str, Any] = {
    "actors": {"tester": {**TESTER, "runner": "theirs", "expect": ["out/ours.txt"]}}
}
MARKERS = b"<<<<<<< HEAD\nexpect: ours\n=======\nrunner: theirs\n>>>>>>> feature\n"


def _recorded(*configs: dict[str, Any]) -> dict[str, frozenset[str]]:
    hashes: dict[str, set[str]] = {}
    for config in configs:
        for path, data in render(config).items():
            hashes.setdefault(path, set()).add(file_hash(data))
    return {path: frozenset(found) for path, found in hashes.items()}


def _conflicted(theatre: Path, working: bytes) -> dict[str, MergeSides]:
    (theatre / ".troupe" / "actors").mkdir(parents=True, exist_ok=True)
    _actor_file(theatre).write_bytes(working)
    (theatre / ".troupe" / MD_FILE).write_bytes(render(OURS)[MD_FILE])
    return {
        YAML_FILE: MergeSides("conflicted", (render(OURS)[YAML_FILE], render(THEIRS)[YAML_FILE]))
    }


def _kept(theatre: Path, kept: str) -> bytes:
    return (
        theatre / ".troupe" / "local" / "artifacts" / "sha256" / kept[7:9] / kept[7:]
    ).read_bytes()


@pytest.mark.parametrize(
    "working",
    [MARKERS, b"expect: ours\nrunner: theirs\n>>>>>>> feature\n"],
    ids=["markers", "half-resolved-by-hand"],
)
def test_a_conflicted_file_from_troupes_versions_is_written_from_the_merged_config_and_kept(
    tmp_path: Path, working: bytes
) -> None:
    theatre = _theatre(tmp_path)
    merged = _conflicted(theatre, working)
    troupe_dir = theatre / ".troupe"
    planned = plan(
        troupe_dir,
        render(MERGED_CONFIG),
        _recorded(OURS, THEIRS),
        merged=merged,
        resolve=frozenset(merged),
    )
    [action] = planned.changes
    assert (action.path, action.action, action.keep, action.merge) == (
        YAML_FILE,
        "write",
        True,
        "conflicted",
    )
    kept = execute(troupe_dir, planned)
    assert _actor_file(theatre).read_bytes() == render(MERGED_CONFIG)[YAML_FILE]
    assert _actor_file(theatre).read_bytes() not in (
        render(OURS)[YAML_FILE],
        render(THEIRS)[YAML_FILE],
    )
    assert _kept(theatre, kept[YAML_FILE]) == working


def test_a_conflicted_file_with_one_side_absent_and_edited_since_is_removed_and_kept(
    tmp_path: Path,
) -> None:
    theatre = _theatre(tmp_path)
    flush(theatre, CONFIG, {})
    # git leaves the surviving side in the file; here the person has since started editing it.
    (theatre / ".troupe" / MD_FILE).write_bytes(b"Changed on the side that kept it, and edited.")
    changed = {"actors": {"tester": {**TESTER, "character": "Changed on the side that kept it."}}}
    merged = {MD_FILE: MergeSides("conflicted", (None, render(changed)[MD_FILE]))}
    no_character = {"actors": {"tester": {k: v for k, v in TESTER.items() if k != "character"}}}
    troupe_dir = theatre / ".troupe"
    planned = plan(
        troupe_dir,
        render(no_character),
        _recorded(changed),
        merged=merged,
        resolve=frozenset(merged),
    )
    [action] = [a for a in planned.changes if a.path == MD_FILE]
    assert (action.action, action.keep) == ("remove", True)
    kept = execute(troupe_dir, planned)
    assert not (troupe_dir / MD_FILE).exists()
    assert _kept(theatre, kept[MD_FILE]) == b"Changed on the side that kept it, and edited."


def test_a_conflicted_file_with_a_side_troupe_didnt_write_is_refused_naming_that_side(
    tmp_path: Path,
) -> None:
    theatre = _theatre(tmp_path)
    merged = _conflicted(theatre, MARKERS)
    with pytest.raises(TroupeError) as caught:
        flush(theatre, MERGED_CONFIG, _recorded(OURS), vcs=_Reports(merged), resolve=True)
    assert caught.value.code == "config.file-not-troupes"
    assert "theirs isn't a version troupe wrote" in caught.value.problem
    assert f"git checkout --ours .troupe/{YAML_FILE}" in caught.value.fix
    assert "troupe flush --force" in caught.value.fix
    check_error(caught.value.to_data())
    assert _actor_file(theatre).read_bytes() == MARKERS


def test_a_clean_merge_still_as_git_made_it_is_written_from_the_merged_config_and_kept(
    tmp_path: Path,
) -> None:
    theatre = _theatre(tmp_path)
    git_merged = b"git's clean merge of the two sides\n"
    _conflicted(theatre, git_merged)
    merged = {
        YAML_FILE: MergeSides(
            "clean", (render(OURS)[YAML_FILE], render(THEIRS)[YAML_FILE]), git_merged
        )
    }
    troupe_dir = theatre / ".troupe"
    planned = plan(
        troupe_dir,
        render(MERGED_CONFIG),
        _recorded(OURS, THEIRS),
        merged=merged,
        resolve=frozenset(merged),
    )
    [action] = planned.changes
    assert (action.action, action.keep, action.merge) == ("write", True, "clean")


def test_a_clean_merge_edited_after_git_made_it_is_refused_as_a_hand_edit(tmp_path: Path) -> None:
    theatre = _theatre(tmp_path)
    _conflicted(theatre, b"git's clean merge, then edited\n")
    merged = {
        YAML_FILE: MergeSides(
            "clean", (render(OURS)[YAML_FILE], render(THEIRS)[YAML_FILE]), b"git's clean merge\n"
        )
    }
    troupe_dir = theatre / ".troupe"
    planned = plan(
        troupe_dir,
        render(MERGED_CONFIG),
        _recorded(OURS, THEIRS),
        merged=merged,
        resolve=frozenset(merged),
    )
    [action] = planned.refused
    assert action.reason == "troupe didn't write it"


def test_a_merged_file_already_a_version_troupe_wrote_is_replaced_with_no_copy(
    tmp_path: Path,
) -> None:
    theatre = _theatre(tmp_path)
    merged = _conflicted(theatre, render(OURS)[YAML_FILE])  # as after git checkout --ours
    troupe_dir = theatre / ".troupe"
    planned = plan(
        troupe_dir,
        render(MERGED_CONFIG),
        _recorded(OURS, THEIRS),
        merged=merged,
        resolve=frozenset(merged),
    )
    [action] = planned.changes
    assert (action.reason, action.keep) == ("an older version troupe wrote", False)
    assert execute(troupe_dir, planned) == {}


def test_a_merged_file_this_command_may_not_resolve_is_refused_naming_flush_and_left_alone(
    tmp_path: Path,
) -> None:
    theatre = _theatre(tmp_path)
    merged = _conflicted(theatre, MARKERS)
    with pytest.raises(TroupeError) as caught:
        flush(theatre, MERGED_CONFIG, _recorded(OURS, THEIRS), vcs=_Reports(merged))
    assert caught.value.code == "config.file-not-troupes"
    assert "git merged it from versions troupe wrote" in caught.value.problem
    assert "Run troupe flush" in caught.value.fix
    check_error(caught.value.to_data())
    assert _actor_file(theatre).read_bytes() == MARKERS
    assert not (theatre / ".troupe" / "local" / "artifacts").exists()


def test_a_staged_write_finished_over_a_merged_file_keeps_the_files_bytes_first(
    tmp_path: Path,
) -> None:
    theatre = _theatre(tmp_path)
    merged = _conflicted(theatre, MARKERS)
    troupe_dir = theatre / ".troupe"
    resolved = render(MERGED_CONFIG)[YAML_FILE]
    stage(troupe_dir, YAML_FILE, resolved)  # what config set stages before recording its change
    recorded = _recorded(OURS, THEIRS, MERGED_CONFIG)
    planned = plan(
        troupe_dir, render(MERGED_CONFIG), recorded, merged=merged, resolve=frozenset(merged)
    )
    [action] = planned.changes
    assert (action.action, action.keep) == ("finish", True)
    kept = execute(troupe_dir, planned)
    assert _actor_file(theatre).read_bytes() == resolved
    assert _kept(theatre, kept[YAML_FILE]) == MARKERS


def test_flushing_a_merged_file_reports_config_merge_rewritten_with_its_kept_hash(
    tmp_path: Path,
) -> None:
    theatre = _theatre(tmp_path)
    merged = _conflicted(theatre, MARKERS)
    flushed = flush(
        theatre, MERGED_CONFIG, _recorded(OURS, THEIRS), vcs=_Reports(merged), resolve=True
    )
    [notice] = [n for n in flushed.notices() if n.path == f".troupe/{YAML_FILE}"]
    assert notice.code == "config.merge-rewritten"
    assert notice.details == {
        "merge": "conflicted",
        "action": "write",
        "kept": file_hash(MARKERS),
        "resolved": False,
        "unresolved": "setting",
    }
    assert f"git add .troupe/{YAML_FILE}" in notice.fix
    check_notice(notice.to_data())


def test_a_rehearsed_flush_of_a_merged_file_names_it_and_its_reason_and_writes_nothing(
    tmp_path: Path,
) -> None:
    theatre = _theatre(tmp_path)
    merged = _conflicted(theatre, MARKERS)
    flushed = flush(
        theatre,
        MERGED_CONFIG,
        _recorded(OURS, THEIRS),
        vcs=_Reports(merged),
        resolve=True,
        rehearse=True,
    )
    [action] = [a for a in flushed.actions if a.path == YAML_FILE]
    assert action.reason == "git left it conflicted, from versions troupe wrote"
    assert _actor_file(theatre).read_bytes() == MARKERS
    assert not (theatre / ".troupe" / "local" / "artifacts").exists()


class _Reports:
    """A VCS reporting ``merged`` (paths relative to .troupe/) as its merge sides, recording each
    call to mark paths resolved and marking every one."""

    def __init__(self, merged: dict[str, MergeSides]) -> None:
        self.merged = merged
        self.marked: list[dict[str, Resolve]] = []

    def merge_sides_under(self, directory: str) -> dict[str, MergeSides]:
        prefix = directory.removeprefix(".troupe/") + "/"
        return {f".troupe/{p}": s for p, s in self.merged.items() if p.startswith(prefix)}

    def mark_resolved(self, paths: Mapping[str, Resolve]) -> Marked:
        self.marked.append(dict(paths))
        return Marked(dict.fromkeys(paths))


# Marking a rewritten unmerged file resolved (spec: config-files, "A rewritten unmerged file is
# marked resolved when the setting is on"; mark-config-resolved design D3, D6). These drive flush
# with a fake VCS; the git adapter's own tests show it marks what it's given.

ON = Marking(True)


def test_a_conflicted_file_rewritten_from_troupes_versions_is_marked_with_the_bytes_written(
    tmp_path: Path,
) -> None:
    theatre = _theatre(tmp_path)
    vcs = _Reports(_conflicted(theatre, MARKERS))
    flushed = flush(
        theatre, MERGED_CONFIG, _recorded(OURS, THEIRS), vcs=vcs, resolve=True, marking=ON
    )
    want = render(MERGED_CONFIG)[YAML_FILE]
    assert vcs.marked == [{f".troupe/{YAML_FILE}": Resolve(vcs.merged[YAML_FILE], want)}]
    assert flushed.resolved == Resolved({YAML_FILE: None})
    [notice] = [n for n in flushed.notices() if n.code == "config.merge-rewritten"]
    assert notice.details["resolved"] is True
    assert "unresolved" not in notice.details
    assert notice.fix.startswith("Commit the merge: troupe marked")
    check_notice(notice.to_data())


def test_an_unmerged_file_already_troupes_and_both_sides_troupes_is_marked_when_rewritten(
    tmp_path: Path,
) -> None:
    theatre = _theatre(tmp_path)
    vcs = _Reports(_conflicted(theatre, render(OURS)[YAML_FILE]))  # as after git checkout --ours
    flushed = flush(theatre, MERGED_CONFIG, _recorded(OURS, THEIRS), vcs=vcs, marking=ON)
    assert list(vcs.marked[0]) == [f".troupe/{YAML_FILE}"]
    [notice] = [n for n in flushed.notices() if n.path == f".troupe/{YAML_FILE}"]
    assert notice.code == "config.file-rewritten"
    assert notice.details["resolved"] is True
    check_notice(notice.to_data())


def test_a_finished_staged_write_over_a_recognised_file_is_marked_with_the_staged_bytes(
    tmp_path: Path,
) -> None:
    theatre = _theatre(tmp_path)
    vcs = _Reports(_conflicted(theatre, MARKERS))
    want = render(MERGED_CONFIG)[YAML_FILE]
    (theatre / ".troupe" / staged_name(YAML_FILE)).write_bytes(want)  # recorded, not moved
    recorded = _recorded(OURS, THEIRS, MERGED_CONFIG)
    flushed = flush(theatre, MERGED_CONFIG, recorded, vcs=vcs, resolve=True, marking=ON)
    [action] = [a for a in flushed.actions if a.action == "finish"]
    assert action.keep
    assert vcs.marked == [{f".troupe/{YAML_FILE}": Resolve(vcs.merged[YAML_FILE], want)}]


def test_a_clean_merge_is_never_marked(tmp_path: Path) -> None:
    theatre = _theatre(tmp_path)
    git_merged = b"git's clean merge of the two sides\n"
    _conflicted(theatre, git_merged)
    vcs = _Reports(
        {
            YAML_FILE: MergeSides(
                "clean", (render(OURS)[YAML_FILE], render(THEIRS)[YAML_FILE]), git_merged
            )
        }
    )
    flushed = flush(
        theatre, MERGED_CONFIG, _recorded(OURS, THEIRS), vcs=vcs, resolve=True, marking=ON
    )
    assert vcs.marked == []
    [notice] = [n for n in flushed.notices() if n.code == "config.merge-rewritten"]
    assert notice.details["resolved"] is False
    assert "unresolved" not in notice.details
    check_notice(notice.to_data())


def test_a_file_forced_past_a_side_troupe_didnt_write_is_never_marked(tmp_path: Path) -> None:
    theatre = _theatre(tmp_path)
    vcs = _Reports(_conflicted(theatre, MARKERS))
    flushed = flush(
        theatre, MERGED_CONFIG, _recorded(OURS), vcs=vcs, resolve=True, force=True, marking=ON
    )
    assert any(a.forced for a in flushed.actions)
    assert vcs.marked == []


def test_an_unmerged_file_already_troupes_with_a_side_troupe_didnt_write_is_never_marked(
    tmp_path: Path,
) -> None:
    theatre = _theatre(tmp_path)
    vcs = _Reports(_conflicted(theatre, render(OURS)[YAML_FILE]))
    flushed = flush(theatre, MERGED_CONFIG, _recorded(OURS), vcs=vcs, marking=ON)
    assert [a.path for a in flushed.actions] == [YAML_FILE]  # rewritten, as an older version
    assert vcs.marked == []


def test_an_unmerged_file_already_what_config_writes_is_left_unmarked(tmp_path: Path) -> None:
    theatre = _theatre(tmp_path)
    vcs = _Reports(_conflicted(theatre, render(MERGED_CONFIG)[YAML_FILE]))
    recorded = _recorded(OURS, THEIRS, MERGED_CONFIG)
    flushed = flush(theatre, MERGED_CONFIG, recorded, vcs=vcs, resolve=True, marking=ON)
    assert flushed.actions == ()
    assert vcs.marked == []


@pytest.mark.parametrize(
    ("marking", "variable"),
    [
        (Marking(False, "setting"), "TROUPE_SETTING_MARK_MERGES_RESOLVED=true"),
        (Marking(False, "policy"), "TROUPE_POLICY_ALLOW_MARK_MERGES_RESOLVED=false"),
    ],
    ids=["setting", "policy"],
)
def test_with_marking_off_nothing_is_marked_and_the_notice_says_why(
    tmp_path: Path, marking: Marking, variable: str
) -> None:
    theatre = _theatre(tmp_path)
    vcs = _Reports(_conflicted(theatre, MARKERS))
    flushed = flush(
        theatre, MERGED_CONFIG, _recorded(OURS, THEIRS), vcs=vcs, resolve=True, marking=marking
    )
    assert vcs.marked == []
    assert _actor_file(theatre).read_bytes() == render(MERGED_CONFIG)[YAML_FILE]
    [notice] = [n for n in flushed.notices() if n.code == "config.merge-rewritten"]
    assert notice.details["resolved"] is False
    assert notice.details["unresolved"] == marking.off_because
    assert f"git add .troupe/{YAML_FILE}" in notice.fix
    assert variable in notice.fix
    assert "#156" not in notice.fix
    check_notice(notice.to_data())


def test_a_rehearsal_marks_nothing_and_says_it_would_mark(tmp_path: Path) -> None:
    theatre = _theatre(tmp_path)
    vcs = _Reports(_conflicted(theatre, MARKERS))
    flushed = flush(
        theatre,
        MERGED_CONFIG,
        _recorded(OURS, THEIRS),
        vcs=vcs,
        resolve=True,
        rehearse=True,
        marking=ON,
    )
    assert vcs.marked == []
    assert flushed.resolved == Resolved({YAML_FILE: None})
    assert _actor_file(theatre).read_bytes() == MARKERS


@pytest.mark.parametrize(
    ("why", "says"),
    [
        ("index-changed", "git's index changed after troupe read it"),
        ("failed", "troupe couldn't mark it resolved (git broke)"),
        ("no-index", "git add .troupe/actors/tester.yaml and commit the merge."),
    ],
)
def test_each_reason_a_file_wasnt_marked_has_its_own_fix(why: str, says: str) -> None:
    action = Action(
        YAML_FILE, "write", "git left it conflicted", b"x", keep=True, merge="conflicted"
    )
    resolved = Resolved({YAML_FILE: why}, "git broke" if why == "failed" else None)  # type: ignore[dict-item]
    [notice] = merge_notices([action], {YAML_FILE: file_hash(b"x")}, resolved)
    assert says in notice.fix
    assert notice.details["unresolved"] == why
    check_notice(notice.to_data())


def test_a_notice_with_an_unknown_reason_for_not_marking_is_invalid() -> None:
    action = Action(
        YAML_FILE, "write", "git left it conflicted", b"x", keep=True, merge="conflicted"
    )
    [notice] = merge_notices([action], {YAML_FILE: file_hash(b"x")}, Resolved({YAML_FILE: None}))
    data = notice.to_data()
    data["details"] = {**data["details"], "resolved": False, "unresolved": "forgot"}
    with pytest.raises(jsonschema.ValidationError):
        check_notice(data)


# Requirement: Force replaces a file and keeps a copy


def test_force_replaces_a_hand_edit_and_names_the_hash_its_bytes_are_kept_under(
    tmp_path: Path,
) -> None:
    theatre = _theatre(tmp_path)
    flush(theatre, CONFIG, {})
    _actor_file(theatre).write_bytes(b"# mine\n")  # these bytes exactly, on Windows too
    flushed = flush(theatre, CONFIG, {}, force=True)
    assert _actor_file(theatre).read_bytes() == render(CONFIG)["actors/tester.yaml"]
    kept = flushed.kept["actors/tester.yaml"]
    assert kept == file_hash(b"# mine\n")
    stored = theatre / ".troupe" / "local" / "artifacts" / "sha256" / kept[7:9] / kept[7:]
    assert stored.read_bytes() == b"# mine\n"


# Requirement: A file is staged beside its target, then replaced atomically


def test_a_staged_write_an_event_vouches_for_is_finished(tmp_path: Path) -> None:
    theatre = _theatre(tmp_path)
    data = render(CONFIG)["actors/tester.yaml"]
    staged = theatre / ".troupe" / staged_name("actors/tester.yaml")
    staged.parent.mkdir(parents=True)
    staged.write_bytes(data)  # recorded, then stopped before the move
    recorded = {"actors/tester.yaml": frozenset({file_hash(data)})}
    flush(theatre, CONFIG, recorded)
    assert _actor_file(theatre).read_bytes() == data
    assert not staged.exists()


def test_a_staged_write_no_event_vouches_for_is_removed(tmp_path: Path) -> None:
    theatre = _theatre(tmp_path)
    staged = theatre / ".troupe" / staged_name("actors/tester.yaml")
    staged.parent.mkdir(parents=True)
    staged.write_bytes(b"staged, then troupe stopped before recording\n")
    flush(theatre, CONFIG, {})
    assert not staged.exists()
    assert _actor_file(theatre).read_bytes() == render(CONFIG)["actors/tester.yaml"]


# Requirement: Config writes queue


def test_a_flush_waits_for_another_process_writing_config_and_says_it_is_waiting(
    tmp_path: Path,
) -> None:
    theatre = _theatre(tmp_path)
    holder = textwrap.dedent(
        f"""
        import sys, time
        from pathlib import Path
        from troupe.core.config.projection import locked
        with locked(Path({str(theatre / ".troupe")!r})):
            print("held", flush=True)
            time.sleep(2.5)
        """
    )
    child = subprocess.Popen([sys.executable, "-c", holder], stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "held"
        waits: list[float] = []
        started = time.monotonic()
        flush(theatre, CONFIG, {}, on_wait=lambda _path, waited: waits.append(waited))
        assert time.monotonic() - started > 1.0
        assert waits
    finally:
        child.wait(timeout=30)
    assert _actor_file(theatre).exists()


def test_the_lock_is_held_for_the_whole_write(tmp_path: Path) -> None:
    theatre = _theatre(tmp_path)
    with locked(theatre / ".troupe"):
        assert (theatre / ".troupe" / "local" / "config").is_dir()


# Requirement: The theatre's git files hold what troupe needs ("Line endings on Windows")


def _checked_out_again(repo: Any, theatre: Path) -> bytes:  # noqa: ANN401
    repo.git("config", "core.autocrlf", "true")
    _actor_file(theatre).unlink()
    repo.git("checkout", "--", ".troupe/actors/tester.yaml")
    return _actor_file(theatre).read_bytes()


def test_a_config_file_checked_out_with_autocrlf_keeps_troupes_line_endings(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    theatre = repo.path
    flush(theatre, CONFIG, {})
    repo.commit_all("tester")
    written = render(CONFIG)["actors/tester.yaml"]
    assert _checked_out_again(repo, theatre) == written
    assert flush(theatre, CONFIG, {}).actions == ()


def test_without_troupes_attribute_autocrlf_would_change_the_file_and_it_would_be_refused(
    tmp_path: Path,
) -> None:
    # The control: shows the test above can fail, so its passing means the attribute works.
    repo = make_repo(tmp_path)
    theatre = repo.path
    flush(theatre, CONFIG, {})
    attributes = theatre / ".troupe" / ".gitattributes"
    attributes.write_text(attributes.read_text("utf-8").replace("actors/** -text", ""), "utf-8")
    repo.commit_all("tester, without the attribute")
    assert b"\r\n" in _checked_out_again(repo, theatre)
    with pytest.raises(TroupeError) as caught:
        flush(theatre, {"actors": {"tester": {**TESTER, "expect": []}}}, {})
    assert caught.value.code == "config.file-not-troupes"


# This clone's record of the files flush wrote


def test_a_torn_last_line_of_the_written_record_is_left_out(tmp_path: Path) -> None:
    theatre = _theatre(tmp_path)
    old = {"actors": {"tester": {**TESTER, "expect": []}}}
    flush(theatre, old, {})
    record = theatre / ".troupe" / WRITTEN
    record.write_bytes(record.read_bytes() + b'{"path":"actors/tes')  # an interrupted append
    flush(theatre, CONFIG, {})  # the earlier lines still vouch for the old file
    assert _actor_file(theatre).read_bytes() == render(CONFIG)["actors/tester.yaml"]


def test_a_malformed_line_before_the_last_is_refused_naming_the_record_and_the_fix(
    tmp_path: Path,
) -> None:
    theatre = _theatre(tmp_path)
    flush(theatre, CONFIG, {})
    record = theatre / ".troupe" / WRITTEN
    record.write_bytes(b"not json\n" + record.read_bytes())
    with pytest.raises(TroupeError) as caught:
        flush(theatre, {"actors": {"tester": {**TESTER, "expect": []}}}, {})
    assert caught.value.code == "config.local-malformed"
    assert caught.value.path == str(record)
    assert "Delete the file" in caught.value.fix
    check_error(caught.value.to_data())


def _reordered(value: object, draw: Any) -> object:  # noqa: ANN401
    if isinstance(value, dict):
        keys = draw(st.permutations(list(value)))
        return {key: _reordered(value[key], draw) for key in keys}
    if isinstance(value, list):
        return [_reordered(item, draw) for item in value]
    return value


@given(st.dictionaries(st.text(min_size=1, max_size=4), JSON, max_size=4), st.data())
def test_a_file_depends_only_on_what_config_holds_not_the_order_values_were_set_in(
    options: dict[str, Any], data: st.DataObject
) -> None:
    # Replaying history sets an actor's values in another order than the command that set them.
    actor = {"runner": "scripted", "options": options, "expect": [], "character": "C."}
    reordered = _reordered(actor, data.draw)
    assert isinstance(reordered, dict)
    assert render_actor(reordered) == render_actor(actor)
