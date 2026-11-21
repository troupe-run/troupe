"""The sweep: classifying config files, working out each hand edit, and recording it (spec:
config-hand-edits; hand-edit-sweep design D3, D4, D5, D7)."""

import json
from pathlib import Path
from typing import Any

import pytest

from configtesting import TESTER
from storetesting import files_service, segments
from troupe.core.config.changes import change, leaves
from troupe.core.config.projection import file_hash, render
from troupe.core.config.stream import read, record, record_with_edits
from troupe.core.config.sweep import sweep
from troupe.core.errors import TroupeError
from troupe.core.events import EventStore
from troupe.core.identity import Identity
from troupe.core.vcs import MergeSides

FIELDS = {k: v for k, v in TESTER.items() if k != "character"}


def _theatre(tmp_path: Path, config: dict[str, Any]) -> tuple[EventStore, Path]:
    """A theatre whose config is ``config``, recorded as one change, with its files written."""
    (tmp_path / ".troupe").mkdir()
    service = files_service(tmp_path)
    merged = read(service)
    operations = [
        ((kind, name), group) for kind, groups in config.items() for name, group in groups.items()
    ]
    entries = change(merged.config, operations)
    files = render(config)
    record(
        service.command(via="cli"),
        merged,
        entries,
        [{"path": p, "hash": file_hash(d)} for p, d in files.items()],
    )
    troupe_dir = tmp_path / ".troupe"
    for path, data in files.items():
        (troupe_dir / path).parent.mkdir(parents=True, exist_ok=True)
        (troupe_dir / path).write_bytes(data)
    return service, troupe_dir


def _sweep(
    service: EventStore, troupe_dir: Path, merged: dict[str, MergeSides] | None = None
) -> Any:  # noqa: ANN401
    current = read(service)
    return sweep(troupe_dir, current.config, current.files, merged or {})


def _yaml(troupe_dir: Path) -> Path:
    return troupe_dir / "actors" / "tester.yaml"


# Requirement: Only a change in values is a change


def test_files_exactly_as_config_renders_them_give_no_edit(tmp_path: Path) -> None:
    service, troupe_dir = _theatre(tmp_path, {"actors": {"tester": TESTER}})
    assert _sweep(service, troupe_dir).edits == ()


def test_a_comment_a_new_order_and_new_indentation_give_no_edit(tmp_path: Path) -> None:
    service, troupe_dir = _theatre(tmp_path, {"actors": {"tester": TESTER}})
    text = _yaml(troupe_dir).read_text()
    lines = text.splitlines(keepends=True)
    # The person's own comment, at the top, and the schema lines moved below it.
    _yaml(troupe_dir).write_text("# the tester, by hand\n" + "".join(lines) + "\n# the end\n")
    assert _sweep(service, troupe_dir).edits == ()


def test_a_changed_value_is_one_entry(tmp_path: Path) -> None:
    service, troupe_dir = _theatre(tmp_path, {"actors": {"tester": TESTER}})
    text = _yaml(troupe_dir).read_text()
    _yaml(troupe_dir).write_text(text + "workspace: theatre\n")
    swept = _sweep(service, troupe_dir)
    [edit] = swept.edits
    assert edit.path == "actors/tester.yaml"
    assert [e["path"] for e in edit.entries] == [["actors", "tester", "workspace"]]
    assert edit.entries[0]["after"] == "theatre"
    assert "before" not in edit.entries[0]


def test_a_character_is_set_whole_from_its_file(tmp_path: Path) -> None:
    service, troupe_dir = _theatre(tmp_path, {"actors": {"tester": TESTER}})
    (troupe_dir / "actors" / "tester.md").write_bytes(b"You are new.\r\n")
    [edit] = _sweep(service, troupe_dir).edits
    assert edit.entries == (
        {
            "path": ["actors", "tester", "character"],
            "before": edit.entries[0]["before"],
            "after": "You are new.\r\n",
        },
    )


def test_an_edit_and_its_undo_give_no_edit(tmp_path: Path) -> None:
    service, troupe_dir = _theatre(tmp_path, {"actors": {"tester": TESTER}})
    original = _yaml(troupe_dir).read_bytes()
    _yaml(troupe_dir).write_bytes(original + b"workspace: theatre\n")
    _yaml(troupe_dir).write_bytes(original)
    assert _sweep(service, troupe_dir).edits == ()


# Requirement: Adding or deleting a file adds or removes what it held


def test_a_new_actor_file_adds_the_actor(tmp_path: Path) -> None:
    service, troupe_dir = _theatre(tmp_path, {"actors": {"tester": TESTER}})
    (troupe_dir / "actors" / "qa.yaml").write_bytes(
        render({"actors": {"qa": FIELDS}})["actors/qa.yaml"]
    )
    [edit] = _sweep(service, troupe_dir).edits
    assert edit.path == "actors/qa.yaml"
    assert {tuple(e["path"]) for e in edit.entries} == set(leaves({"actors": {"qa": FIELDS}}))
    assert edit.before is None


def test_a_deleted_character_file_unsets_the_character(tmp_path: Path) -> None:
    service, troupe_dir = _theatre(tmp_path, {"actors": {"tester": TESTER}})
    (troupe_dir / "actors" / "tester.md").unlink()
    [edit] = _sweep(service, troupe_dir).edits
    assert [e["path"] for e in edit.entries] == [["actors", "tester", "character"]]
    assert "after" not in edit.entries[0]
    assert edit.after is None
    assert edit.files == ({"path": "actors/tester.md"},)


def test_deleting_both_files_removes_the_actor_as_one_entry(tmp_path: Path) -> None:
    service, troupe_dir = _theatre(tmp_path, {"actors": {"tester": TESTER}})
    (troupe_dir / "actors" / "tester.md").unlink()
    _yaml(troupe_dir).unlink()
    [edit] = _sweep(service, troupe_dir).edits
    assert [e["path"] for e in edit.entries] == [["actors", "tester"]]
    assert edit.files == ({"path": "actors/tester.yaml"}, {"path": "actors/tester.md"})


def test_a_character_left_without_its_actors_yaml_is_refused(tmp_path: Path) -> None:
    service, troupe_dir = _theatre(tmp_path, {"actors": {"tester": TESTER}})
    _yaml(troupe_dir).unlink()
    with pytest.raises(TroupeError) as caught:
        _sweep(service, troupe_dir)
    assert caught.value.code == "config.file-invalid"
    assert ".troupe/actors/tester.md" in caught.value.problem
    assert "delete this file too" in caught.value.fix


def test_a_deleted_runtime_file_removes_the_runtime(tmp_path: Path) -> None:
    service, troupe_dir = _theatre(tmp_path, {"runtimes": {"openai": {"model": "m"}}})
    (troupe_dir / "runtimes" / "openai.yaml").unlink()
    [edit] = _sweep(service, troupe_dir).edits
    assert [e["path"] for e in edit.entries] == [["runtimes", "openai"]]


# Requirement: A restored file is recorded as an edit (the file wins)


def test_an_older_version_troupe_wrote_is_read_as_an_edit(tmp_path: Path) -> None:
    service, troupe_dir = _theatre(tmp_path, {"actors": {"tester": TESTER}})
    older = _yaml(troupe_dir).read_bytes()
    current = read(service)
    entries = change(current.config, [(("actors", "tester", "workspace"), "theatre")])
    newer = render({"actors": {"tester": {**TESTER, "workspace": "theatre"}}})["actors/tester.yaml"]
    record(
        service.command(via="cli"),
        current,
        entries,
        [{"path": "actors/tester.yaml", "hash": file_hash(newer)}],
    )
    _yaml(troupe_dir).write_bytes(older)  # git restore, back to a version troupe wrote
    [edit] = _sweep(service, troupe_dir).edits
    assert edit.entries == (
        {"path": ["actors", "tester", "workspace"], "before": edit.entries[0]["before"]},
    )


# Requirement: A file git merged from troupe's versions isn't read as an edit


def _merge(kind: str, ours: bytes, theirs: bytes, merged: bytes | None = None) -> MergeSides:
    return MergeSides(kind=kind, sides=(ours, theirs), merged=merged)  # type: ignore[arg-type]


def test_a_clean_merge_still_as_git_made_it_isnt_read(tmp_path: Path) -> None:
    service, troupe_dir = _theatre(tmp_path, {"actors": {"tester": TESTER}})
    ours = _yaml(troupe_dir).read_bytes()
    theirs = render({"actors": {"tester": {**TESTER, "workspace": "worktree"}}})[
        "actors/tester.yaml"
    ]
    current = read(service)
    record(
        service.command(via="cli"),
        current,
        change(current.config, [(("actors", "tester", "workspace"), "worktree")]),
        [{"path": "actors/tester.yaml", "hash": file_hash(theirs)}],
    )
    gitmade = ours + b"workspace: theatre\n"
    _yaml(troupe_dir).write_bytes(gitmade)
    merges = {"actors/tester.yaml": _merge("clean", ours, theirs, gitmade)}
    assert _sweep(service, troupe_dir, merges).edits == ()


def test_a_conflicted_file_with_its_markers_isnt_read(tmp_path: Path) -> None:
    service, troupe_dir = _theatre(tmp_path, {"actors": {"tester": TESTER}})
    ours = _yaml(troupe_dir).read_bytes()
    _yaml(troupe_dir).write_bytes(b"<<<<<<< ours\nrunner: a\n=======\nrunner: b\n>>>>>>> theirs\n")
    merges = {"actors/tester.yaml": _merge("conflicted", ours, ours)}
    assert _sweep(service, troupe_dir, merges).edits == ()


def test_a_conflict_resolved_by_hand_is_read_as_an_edit(tmp_path: Path) -> None:
    service, troupe_dir = _theatre(tmp_path, {"actors": {"tester": TESTER}})
    ours = _yaml(troupe_dir).read_bytes()
    _yaml(troupe_dir).write_bytes(ours + b"workspace: theatre\n")
    merges = {"actors/tester.yaml": _merge("conflicted", ours, ours)}
    [edit] = _sweep(service, troupe_dir, merges).edits
    assert edit.entries[0]["after"] == "theatre"


# Requirement: An invalid file is refused, never skipped


def test_one_invalid_file_stops_every_files_edit(tmp_path: Path) -> None:
    service, troupe_dir = _theatre(tmp_path, {"actors": {"tester": TESTER, "reviewer": TESTER}})
    _yaml(troupe_dir).write_bytes(_yaml(troupe_dir).read_bytes() + b"workspace: theatre\n")
    (troupe_dir / "actors" / "reviewer.yaml").write_bytes(b"")
    with pytest.raises(TroupeError) as caught:
        _sweep(service, troupe_dir)
    assert caught.value.code == "config.file-invalid"
    assert "reviewer.yaml" in caught.value.problem


def test_a_rule_the_values_break_is_refused_naming_the_file(tmp_path: Path) -> None:
    service, troupe_dir = _theatre(tmp_path, {"actors": {"tester": TESTER}})
    _yaml(troupe_dir).write_bytes(_yaml(troupe_dir).read_bytes() + b"runnr: x\n")
    with pytest.raises(TroupeError) as caught:
        _sweep(service, troupe_dir)
    assert caught.value.code == "config.file-invalid"
    assert caught.value.details["path"] == ["actors", "tester", "runnr"]


def test_an_unknown_file_is_refused_before_anything_is_read(tmp_path: Path) -> None:
    service, troupe_dir = _theatre(tmp_path, {"actors": {"tester": TESTER}})
    (troupe_dir / "actors" / "notes.txt").write_text("x")
    with pytest.raises(TroupeError) as caught:
        _sweep(service, troupe_dir)
    assert caught.value.code == "config.unknown-file"


# Requirement: troupe's own writes are never read as edits


def test_a_staged_write_a_change_vouches_for_isnt_read(tmp_path: Path) -> None:
    service, troupe_dir = _theatre(tmp_path, {"actors": {"tester": TESTER}})
    current = read(service)
    newer = render({"actors": {"tester": {**TESTER, "workspace": "theatre"}}})["actors/tester.yaml"]
    record(
        service.command(via="cli"),
        current,
        change(current.config, [(("actors", "tester", "workspace"), "theatre")]),
        [{"path": "actors/tester.yaml", "hash": file_hash(newer)}],
    )
    (troupe_dir / "actors" / ".tester.yaml.troupe~").write_bytes(newer)  # a crash before the move
    assert _sweep(service, troupe_dir).edits == ()


# Requirement: Each edited file is recorded as its own change by an unknown author


def _lines(theatre: Path) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for path in segments(theatre):
        found.extend(json.loads(raw) for raw in path.read_bytes().splitlines()[1:])
    return found


def test_each_edited_file_is_its_own_change_by_the_unknown_author(tmp_path: Path) -> None:
    service, troupe_dir = _theatre(tmp_path, {"actors": {"tester": TESTER, "reviewer": TESTER}})
    before = file_hash(_yaml(troupe_dir).read_bytes())
    _yaml(troupe_dir).write_bytes(_yaml(troupe_dir).read_bytes() + b"workspace: theatre\n")
    (troupe_dir / "actors" / "reviewer.md").write_bytes(b"New.")
    swept = _sweep(service, troupe_dir)
    record_with_edits(service, read(service), swept.edits)
    first, second = (line["state"] for line in _lines(tmp_path)[-2:])
    assert first["lineage"]["actor"] == {"kind": "unknown"}
    assert first["lineage"]["via"] == "file"
    assert "reason" not in first["lineage"]
    assert first["lineage"]["vcs"]["source"]["path"] == ".troupe/actors/reviewer.md"
    assert second["lineage"]["vcs"]["source"] == {
        "path": ".troupe/actors/tester.yaml",
        "before": before,
        "after": file_hash(_yaml(troupe_dir).read_bytes()),
    }
    assert second["files"] == [
        {"path": "actors/tester.yaml", "hash": file_hash(_yaml(troupe_dir).read_bytes())}
    ]
    assert first["lineage"]["change"] == second["lineage"]["change"]
    assert read(service).config["actors"]["tester"]["workspace"] == "theatre"
    assert read(service).config["actors"]["reviewer"]["character"] == "New."


def test_the_sweeps_change_id_differs_from_the_commands(tmp_path: Path) -> None:
    service, troupe_dir = _theatre(tmp_path, {"actors": {"tester": TESTER}})
    _yaml(troupe_dir).write_bytes(_yaml(troupe_dir).read_bytes() + b"workspace: theatre\n")
    current = read(service)
    swept = _sweep(service, troupe_dir)
    swept_config = current.config
    from troupe.core.config.changes import apply

    swept_config = apply(current.config, swept.entries)
    own = change(swept_config, [(("actors", "tester", "expect"), ["out/hello.txt", "out/b.txt"])])
    record_with_edits(service, current, swept.edits, (service.command(via="cli"), own, []))
    edit, person = (line["state"]["lineage"] for line in _lines(tmp_path)[-2:])
    assert edit["actor"] == {"kind": "unknown"}
    assert person["actor"]["kind"] == "human"
    assert edit["change"] != person["change"]


def test_with_the_author_named_in_the_environment_the_hand_edit_is_still_unknown(
    tmp_path: Path,
) -> None:
    service, troupe_dir = _theatre(tmp_path, {"actors": {"tester": TESTER}})
    assert isinstance(service.identify(), Identity)  # the environment names a person
    _yaml(troupe_dir).write_bytes(_yaml(troupe_dir).read_bytes() + b"workspace: theatre\n")
    record_with_edits(service, read(service), _sweep(service, troupe_dir).edits)
    assert _lines(tmp_path)[-1]["state"]["lineage"]["actor"] == {"kind": "unknown"}


def test_after_recording_the_next_sweep_finds_nothing(tmp_path: Path) -> None:
    service, troupe_dir = _theatre(tmp_path, {"actors": {"tester": TESTER}})
    _yaml(troupe_dir).write_text(
        "# mine\n" + _yaml(troupe_dir).read_text() + "workspace: theatre\n"
    )
    record_with_edits(service, read(service), _sweep(service, troupe_dir).edits)
    assert _sweep(service, troupe_dir).edits == ()
