"""Config's files: the kinds of file, rendering them, the check before replacing one, staged writes
and flush (spec: config-files; config-model design D7, D8, D9)."""

import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Any

import pytest
import yaml as yaml_1_1  # type: ignore[import-untyped]  # PyYAML reads YAML 1.1, as many editors do
from hypothesis import example, given
from hypothesis import strategies as st
from ruamel.yaml import YAML

from configtesting import TESTER
from gitrepo import make_repo
from protocol_schemas import PROTOCOL_BASE, SCRIPTED, check_error, check_notice, validator_for
from troupe.core.config.kinds import file_kind, staged_name, staged_target
from troupe.core.config.projection import (
    WRITTEN,
    file_hash,
    flush,
    locked,
    on_disk,
    render,
    render_actor,
)
from troupe.core.errors import TroupeError

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
