"""Syncing config with its files in one step: the sweep, a command's own change, and the write,
over a theatre with no version control (spec: config-hand-edits, config-files; hand-edit-sweep
design D1, D7-D11).

Its tests that use a git theatre are in integration/test_config_sync.py. Conflicting config comes
from two clones' event segments put side by side, as a merge of their branches does."""

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from configtesting import TESTER
from storetesting import ADA, files_service
from troupe.core.config import aggregate
from troupe.core.config.changes import Rename
from troupe.core.config.stream import read
from troupe.core.config.syncing import Request, Synced, file_notices, sync_config
from troupe.core.errors import TroupeError
from troupe.core.events import EventStore
from troupe.core.identity import Identity
from troupe_store_text.store import TextStore
from troupe_vcs_files import FilesAdapter

TESTER_PATH = ("actors", "tester")
WORKSPACE = ("actors", "tester", "workspace")
YAML = "actors/tester.yaml"
MD = "actors/tester.md"


@pytest.fixture
def theatre(tmp_path: Path) -> Path:
    made = tmp_path / "theatre"
    (made / ".troupe").mkdir(parents=True)
    return made


class _Uncommitted(FilesAdapter):
    """The files adapter with nothing committed, as git sees new event segments, so a round trip
    a sweep closes can be dropped (abandoned-edits design D5)."""

    def committed_under(self, directory: str) -> frozenset[str]:
        del directory
        return frozenset()


def _store(theatre: Path, *, committed: bool = True) -> EventStore:
    if committed:
        return files_service(theatre)
    vcs = _Uncommitted(theatre)
    return EventStore(theatre, vcs=vcs, recorder=TextStore(theatre, vcs), env=ADA)


def _sync(
    theatre: Path,
    *operations: tuple[tuple[str, ...], object],
    committed: bool = True,
    **request: Any,  # noqa: ANN401
) -> Synced:
    store = _store(theatre, committed=committed)
    return sync_config(theatre, store, Request(operations=operations, **request))


def _events(theatre: Path) -> list[Any]:
    return _store(theatre).history(aggregate.STREAM)


def _file(theatre: Path, path: str = YAML) -> Path:
    return theatre / ".troupe" / path


def _append(theatre: Path, line: str, path: str = YAML) -> None:
    file = _file(theatre, path)
    file.write_text(file.read_text("utf-8") + line + "\n", encoding="utf-8")


def _tester(theatre: Path) -> Synced:
    return _sync(theatre, (TESTER_PATH, TESTER), reason="the tester")


def _change_of(event: Any) -> str:  # noqa: ANN401
    found: str = event.lineage["change"]
    return found


Operations = tuple[tuple[tuple[str, ...], object], ...]


def _conflicted(
    theatre: Path,
    tmp_path: Path,
    ours: Operations = ((WORKSPACE, "theatre"),),
    theirs: Operations = ((WORKSPACE, "worktree"),),
    *,
    also: Operations = (),
) -> None:
    """Two clones each make a change (by default, setting the tester's workspace), and their event
    segments are put together. The actors' files are put back as they were before either, which
    is what config renders: the conflicting values are set by neither."""
    _sync(theatre, (TESTER_PATH, TESTER), *also, reason="the tester")
    actors = theatre / ".troupe" / "actors"
    base = {f.name: f.read_bytes() for f in actors.iterdir()}
    other = tmp_path / "other"
    shutil.copytree(theatre, other)
    shutil.rmtree(other / ".troupe" / "local")
    _sync(theatre, *ours)
    _sync(other, *theirs)
    for segment in (other / ".troupe" / "events").iterdir():
        mine = theatre / ".troupe" / "events" / segment.name
        if not mine.exists():
            shutil.copy(segment, mine)
    for file in actors.iterdir():
        if file.name not in base:
            file.unlink()
    for name, data in base.items():
        (actors / name).write_bytes(data)
    assert read(_store(theatre)).conflicts


def _conflict_changes(theatre: Path) -> list[str]:
    return [c.change for c in read(_store(theatre)).conflicts[0].changes]


# Nothing to do


def test_a_sync_with_nothing_to_do_records_and_writes_nothing(theatre: Path) -> None:
    synced = _sync(theatre)
    assert synced.edits == ()
    assert synced.sweep_change is None
    assert synced.change is None
    assert synced.entries == []
    assert synced.own == frozenset()
    assert synced.notices == []
    assert synced.merged.config == {}
    assert _events(theatre) == []
    assert file_notices(synced) == []


# A command's own change


def test_a_commands_change_is_recorded_and_its_files_written(theatre: Path) -> None:
    synced = _tester(theatre)
    (event,) = _events(theatre)
    assert synced.change == _change_of(event)
    assert event.lineage["reason"] == "the tester"
    assert synced.own == frozenset({YAML, MD})
    assert sorted(e["path"][2] for e in synced.entries) == [
        "character",
        "effects",
        "expect",
        "options",
        "options",
        "runner",
    ]
    assert synced.merged.config["actors"]["tester"]["runner"] == "scripted"
    assert _file(theatre, MD).read_text("utf-8") == "You are the tester."
    assert "runner: scripted" in _file(theatre).read_text("utf-8")
    assert synced.edits == ()
    assert synced.sweep_change is None
    assert synced.notices == []
    assert file_notices(synced) == []
    assert not list((theatre / ".troupe" / "actors").glob(".*.troupe~"))


def test_a_change_that_changes_nothing_records_nothing(theatre: Path) -> None:
    _tester(theatre)
    synced = _sync(theatre, (("actors", "tester", "runner"), "scripted"))
    assert len(_events(theatre)) == 1
    assert synced.change is None
    assert synced.entries == []
    assert synced.own == frozenset()


def test_the_actor_given_is_the_changes_actor(theatre: Path) -> None:
    actor = Identity(kind="human", id="bob@example.com", source="flag")
    _sync(theatre, (TESTER_PATH, TESTER), actor=actor)
    (event,) = _events(theatre)
    assert event.lineage["actor"]["id"] == "bob@example.com"
    assert event.lineage["actor"]["source"] == "flag"


def test_a_sync_holds_the_config_lock_and_a_rehearsal_doesnt(
    theatre: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from contextlib import contextmanager

    from troupe.core.config import syncing

    held: list[tuple[Path, object]] = []

    @contextmanager
    def locked(troupe_dir: Path, on_wait: object = None) -> Iterator[None]:
        held.append((troupe_dir, on_wait))
        yield

    def on_wait(command: str, seconds: float) -> None:
        del command, seconds

    monkeypatch.setattr(syncing, "locked", locked)
    _sync(theatre, (TESTER_PATH, TESTER), rehearse=True, on_wait=on_wait)
    assert held == []
    _sync(theatre, (TESTER_PATH, TESTER), on_wait=on_wait)
    assert held == [(theatre / ".troupe", on_wait)]


def test_a_rehearsed_change_writes_and_records_nothing(theatre: Path) -> None:
    synced = _sync(theatre, (TESTER_PATH, TESTER), rehearse=True)
    assert _events(theatre) == []
    assert not _file(theatre).exists()
    assert not (theatre / ".troupe" / "local").exists()
    assert synced.change is None
    assert synced.own == frozenset({YAML, MD})
    assert {a.path for a in synced.actions} == {YAML, MD}
    assert synced.merged.config["actors"]["tester"]["runner"] == "scripted"
    assert len(synced.entries) == 6
    assert synced.notices == []


# Hand edits


def test_a_hand_edit_is_recorded_by_an_unknown_author_and_named(theatre: Path) -> None:
    _tester(theatre)
    _append(theatre, "workspace: theatre")
    synced = _sync(theatre)
    *_, edit = _events(theatre)
    assert edit.lineage["actor"] == {"kind": "unknown"}
    assert synced.sweep_change == _change_of(edit)
    assert synced.change is None
    assert [e.path for e in synced.edits] == [YAML]
    assert synced.merged.config["actors"]["tester"]["workspace"] == "theatre"
    (notice,) = synced.notices
    assert notice.code == "config.hand-edit-recorded"
    assert notice.problem == (
        "troupe recorded the edit to .troupe/actors/tester.yaml, as a change by an unknown "
        "author (1 value)."
    )
    assert notice.fix == "Nothing to do: the file is what config says now."
    assert notice.details == {
        "file": ".troupe/actors/tester.yaml",
        "entries": 1,
        "change": synced.sweep_change,
    }


def test_a_hand_edit_of_two_values_counts_them(theatre: Path) -> None:
    _tester(theatre)
    _append(theatre, "workspace: theatre\nonContextFull: fail")
    (notice,) = _sync(theatre).notices
    assert "(2 values)" in notice.problem
    assert notice.details["entries"] == 2


def test_a_removed_file_is_recorded_as_removing_what_it_held(theatre: Path) -> None:
    _tester(theatre)
    _file(theatre, MD).unlink()
    synced = _sync(theatre)
    notice, abandoned = synced.notices
    assert abandoned.code == "config.edit-abandoned"
    assert abandoned.details["change"] == synced.sweep_change
    assert notice.problem == (
        "troupe recorded .troupe/actors/tester.md going missing as removing what it held, as a "
        "change by an unknown author (1 value)."
    )
    assert notice.details == {
        "file": ".troupe/actors/tester.md",
        "entries": 1,
        "change": synced.sweep_change,
        "removed": True,
    }
    assert "character" not in synced.merged.config["actors"]["tester"]


def test_a_rehearsed_hand_edit_would_be_recorded(theatre: Path) -> None:
    _tester(theatre)
    _append(theatre, "workspace: theatre")
    synced = _sync(theatre, rehearse=True)
    assert len(_events(theatre)) == 1
    assert [e.path for e in synced.edits] == [YAML]
    assert synced.sweep_change is None
    assert synced.merged.config["actors"]["tester"]["workspace"] == "theatre"
    (notice,) = synced.notices
    assert notice.problem == (
        "troupe would record the edit to .troupe/actors/tester.yaml, as a change by an unknown "
        "author (1 value)."
    )
    assert notice.details == {"file": ".troupe/actors/tester.yaml", "entries": 1, "rehearsal": True}


def test_a_hand_edit_and_a_change_are_recorded_together(theatre: Path) -> None:
    _tester(theatre)
    _append(theatre, "workspace: theatre")
    synced = _sync(theatre, (("actors", "tester", "character"), "You are new."), reason="why")
    _, edit, own = _events(theatre)
    assert synced.sweep_change == _change_of(edit)
    assert synced.change == _change_of(own)
    assert synced.sweep_change != synced.change
    assert own.lineage["reason"] == "why"
    assert synced.own == frozenset({MD})
    assert _file(theatre, MD).read_text("utf-8") == "You are new."
    assert synced.merged.config["actors"]["tester"]["workspace"] == "theatre"
    assert [n.code for n in synced.notices] == ["config.hand-edit-recorded"]
    assert synced.notices[0].details["change"] == synced.sweep_change


def test_a_hand_move_is_recorded_as_a_rename(theatre: Path) -> None:
    _tester(theatre)
    for path in (YAML, MD):
        old = _file(theatre, path)
        old.rename(old.with_name(old.name.replace("tester", "checker")))
    synced = _sync(theatre)
    assert "checker" in synced.merged.config["actors"]
    assert "tester" not in synced.merged.config["actors"]
    (notice,) = synced.notices
    assert notice.code == "config.hand-move-recorded"
    assert notice.problem == (
        "troupe recorded the files moved to .troupe/actors/checker.yaml as renaming "
        "actors.tester to actors.checker, by an unknown author."
    )
    assert notice.fix == "Nothing to do: its history and runs follow it to the new name."
    assert notice.details == {
        "file": ".troupe/actors/checker.yaml",
        "from": "actors.tester",
        "to": "actors.checker",
        "change": synced.sweep_change,
    }


def test_a_rehearsed_hand_move_would_be_recorded(theatre: Path) -> None:
    _tester(theatre)
    for path in (YAML, MD):
        old = _file(theatre, path)
        old.rename(old.with_name(old.name.replace("tester", "checker")))
    (notice,) = _sync(theatre, rehearse=True).notices
    assert notice.problem.startswith("troupe would record the files moved to ")
    assert notice.details == {
        "file": ".troupe/actors/checker.yaml",
        "from": "actors.tester",
        "to": "actors.checker",
        "rehearsal": True,
    }


# Renames


def test_a_rename_moves_the_files_and_records_it(theatre: Path) -> None:
    _tester(theatre)
    synced = _sync(theatre, (("actors", "checker"), Rename(TESTER_PATH)))
    assert synced.change is not None
    assert synced.edits == ()
    assert _file(theatre, "actors/checker.yaml").is_file()
    assert not _file(theatre).exists()
    assert synced.own == frozenset({YAML, MD, "actors/checker.yaml", "actors/checker.md"})
    assert list(synced.merged.config["actors"]) == ["checker"]


def test_a_rename_of_files_already_moved_by_hand_records_the_rename_first(theatre: Path) -> None:
    _tester(theatre)
    for path in (YAML, MD):
        old = _file(theatre, path)
        old.rename(old.with_name(old.name.replace("tester", "checker")))
    _append(theatre, "workspace: theatre", "actors/checker.yaml")
    synced = _sync(theatre, (("actors", "checker"), Rename(TESTER_PATH)))
    _, rename, edit = _events(theatre)
    assert synced.change == _change_of(rename)
    assert synced.sweep_change == _change_of(edit)
    assert synced.merged.config["actors"] == {
        "checker": {**synced.merged.config["actors"]["checker"], "workspace": "theatre"}
    }
    assert [n.code for n in synced.notices] == ["config.hand-edit-recorded"]


def test_a_rename_to_a_bad_name_is_refused_before_anything_is_recorded(theatre: Path) -> None:
    _tester(theatre)
    with pytest.raises(TroupeError):
        _sync(theatre, (("runtimes", "checker"), Rename(TESTER_PATH)))
    assert len(_events(theatre)) == 1


def test_a_rename_already_moved_to_a_bad_name_is_refused(theatre: Path) -> None:
    _tester(theatre)
    _file(theatre).rename(_file(theatre, "actors/checker.yaml"))
    _file(theatre, MD).unlink()
    with pytest.raises(TroupeError):
        _sync(theatre, (("actors", "checker", "x"), Rename(TESTER_PATH)))
    assert len(_events(theatre)) == 1


# config get's sync: recorded, nothing written


def test_config_gets_sync_records_a_hand_edit_and_writes_no_file(theatre: Path) -> None:
    _tester(theatre)
    _file(theatre, MD).unlink()
    synced = _sync(theatre, query=True)
    *_, edit = _events(theatre)
    assert synced.sweep_change == _change_of(edit)
    assert [e.path for e in synced.edits] == [MD]
    assert synced.actions == ()
    assert [n.code for n in synced.notices] == [
        "config.hand-edit-recorded",
        "config.edit-abandoned",
    ]
    assert [n.details["change"] for n in synced.notices] == [synced.sweep_change] * 2
    assert "character" not in synced.merged.config["actors"]["tester"]


def test_config_gets_sync_with_no_edit_records_nothing(theatre: Path) -> None:
    _tester(theatre)
    synced = _sync(theatre, query=True)
    assert len(_events(theatre)) == 1
    assert synced.merged == read(_store(theatre))
    assert synced.edits == ()
    assert synced.sweep_change is None
    assert synced.notices == []


def test_config_gets_rehearsed_sync_would_record(theatre: Path) -> None:
    _tester(theatre)
    _append(theatre, "workspace: theatre")
    synced = _sync(theatre, query=True, rehearse=True)
    assert len(_events(theatre)) == 1
    assert [e.path for e in synced.edits] == [YAML]
    assert synced.sweep_change is None
    assert synced.merged.config["actors"]["tester"]["workspace"] == "theatre"
    assert [n.details.get("rehearsal") for n in synced.notices] == [True]


# Conflicts


def test_a_command_with_nothing_to_record_is_refused_while_config_conflicts(
    theatre: Path, tmp_path: Path
) -> None:
    _conflicted(theatre, tmp_path)
    with pytest.raises(TroupeError) as caught:
        _sync(theatre)
    assert caught.value.code == "config.conflict"


def test_config_get_shows_conflicting_config_without_refusing(
    theatre: Path, tmp_path: Path
) -> None:
    _conflicted(theatre, tmp_path)
    synced = _sync(theatre, query=True)
    assert len(synced.merged.conflicts) == 1
    assert synced.notices == []
    assert synced.edits == ()


def test_config_get_leaves_a_hand_edit_unrecorded_while_it_leaves_conflicts(
    theatre: Path, tmp_path: Path
) -> None:
    _conflicted(theatre, tmp_path)
    events = len(_events(theatre))
    _append(theatre, "onContextFull: fail")
    synced = _sync(theatre, query=True)
    assert len(_events(theatre)) == events
    (notice,) = synced.notices
    assert notice.code == "config.hand-edit-unrecorded"
    assert notice.problem == (
        "Edits to .troupe/actors/tester.yaml aren't recorded yet: config has conflicts, and they "
        "leave actors.tester.workspace unresolved."
    )
    assert notice.fix == (
        "Set every conflicting value, in the files or with troupe config set; config get shows "
        "both sides."
    )
    assert notice.details == {
        "files": [".troupe/actors/tester.yaml"],
        "left": [list(WORKSPACE)],
    }


def test_a_hand_edit_that_resolves_a_conflict_is_recorded_and_says_so(
    theatre: Path, tmp_path: Path
) -> None:
    _conflicted(theatre, tmp_path)
    changes = _conflict_changes(theatre)
    _append(theatre, "workspace: worktree")
    synced = _sync(theatre)
    assert read(_store(theatre)).conflicts == ()
    *_, edit = _events(theatre)
    assert edit.lineage["actor"] == {"kind": "unknown"}
    assert synced.sweep_change == _change_of(edit)
    codes = [n.code for n in synced.notices]
    assert codes == ["config.hand-edit-recorded", "config.conflict-resolved"]
    resolved = synced.notices[1]
    assert resolved.problem == (
        "The edit to .troupe/actors/tester.yaml resolved the conflict on "
        f'actors.tester.workspace: it took "worktree", over the changes {", ".join(changes)}.'
    )
    assert resolved.fix == "Nothing to do if that's what you meant; otherwise set the value again."
    assert resolved.details == {
        "path": list(WORKSPACE),
        "file": ".troupe/actors/tester.yaml",
        "changes": changes,
        "value": "worktree",
    }


def test_config_get_records_a_hand_edit_that_resolves_every_conflict(
    theatre: Path, tmp_path: Path
) -> None:
    _conflicted(theatre, tmp_path)
    _file(theatre, MD).unlink()
    _file(theatre).unlink()
    synced = _sync(theatre, query=True)
    assert read(_store(theatre)).conflicts == ()
    *_, edit = _events(theatre)
    assert synced.sweep_change == _change_of(edit)
    resolved = synced.notices[-1]
    assert resolved.code == "config.conflict-resolved"
    assert "it unset it, over the changes" in resolved.problem
    assert resolved.details["unset"] is True
    assert "value" not in resolved.details


def test_a_rehearsed_resolution_would_resolve(theatre: Path, tmp_path: Path) -> None:
    _conflicted(theatre, tmp_path)
    events = len(_events(theatre))
    _append(theatre, "workspace: worktree")
    synced = _sync(theatre, rehearse=True)
    assert len(_events(theatre)) == events
    resolved = synced.notices[-1]
    assert " would resolve the conflict on " in resolved.problem
    assert resolved.details["rehearsal"] is True
    assert synced.notices[0].problem.startswith("troupe would record ")


def test_a_commands_change_that_resolves_a_conflict_is_recorded(
    theatre: Path, tmp_path: Path
) -> None:
    _conflicted(theatre, tmp_path)
    synced = _sync(theatre, (WORKSPACE, "worktree"))
    assert synced.change is not None
    assert read(_store(theatre)).conflicts == ()
    assert synced.notices == []
    assert "workspace: worktree" in _file(theatre).read_text("utf-8")


def test_a_change_that_leaves_a_conflict_is_refused(theatre: Path, tmp_path: Path) -> None:
    _conflicted(theatre, tmp_path)
    events = len(_events(theatre))
    with pytest.raises(TroupeError) as caught:
        _sync(theatre, (("actors", "tester", "character"), "You are new."))
    assert caught.value.code == "config.conflict"
    assert len(_events(theatre)) == events


def test_only_the_edit_that_sets_a_conflicting_value_resolves_it(
    theatre: Path, tmp_path: Path
) -> None:
    _conflicted(theatre, tmp_path)
    _append(theatre, "workspace: worktree")
    _append(theatre, " Still.", MD)
    synced = _sync(theatre)
    assert [e.path for e in synced.edits] == [MD, YAML]
    resolved = [n for n in synced.notices if n.code == "config.conflict-resolved"]
    assert [n.details["file"] for n in resolved] == [".troupe/actors/tester.yaml"]


# Round trips a sweep closes (abandoned-edits design D5)


def _round_trip(theatre: Path) -> None:
    """The tester's workspace set, then taken out of its file by hand: the file is back as it
    was."""
    _tester(theatre)
    _sync(theatre, (WORKSPACE, "theatre"))
    text = _file(theatre).read_text("utf-8").replace("workspace: theatre\n", "")
    _file(theatre).write_text(text, encoding="utf-8")


def test_troupe_sync_asks_again_about_a_round_trip_it_can_drop(theatre: Path) -> None:
    _round_trip(theatre)
    first = _sync(theatre, committed=False)
    assert [n.code for n in first.notices] == ["config.hand-edit-recorded", "config.edit-abandoned"]
    assert first.notices[1].details["droppable"] is True
    assert _sync(theatre, committed=False).notices == []
    (again,) = _sync(theatre, committed=False, resolve_all=True).notices
    assert again.code == "config.edit-abandoned"
    assert again.details["changes"] == first.notices[1].details["changes"]


def test_a_round_trip_closed_by_performs_sync_cant_be_dropped(theatre: Path) -> None:
    _round_trip(theatre)
    synced = _sync(theatre, committed=False, runs_now=True)
    assert synced.notices[1].details["droppable"] is False
    assert synced.notices[1].details["reason"] == "run"


# A recording that fails


def test_a_failed_recording_leaves_no_staged_file(
    theatre: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from troupe.core.config import syncing

    def fail(*_: object, **__: object) -> None:
        raise OSError("the disk is full")

    monkeypatch.setattr(syncing, "record_with_edits", fail)
    with pytest.raises(OSError, match="the disk is full"):
        _tester(theatre)
    assert _events(theatre) == []
    assert sorted(p.name for p in (theatre / ".troupe").rglob("*.troupe~")) == []
    assert not _file(theatre).exists()


def test_a_resolved_value_is_shown_as_written(theatre: Path, tmp_path: Path) -> None:
    character = ("actors", "tester", "character")
    _conflicted(theatre, tmp_path, ((character, "Tu es là."),), ((character, "Du bist da."),))
    _file(theatre, MD).write_text("Tu es testé.", encoding="utf-8")
    resolved = _sync(theatre).notices[-1]
    assert resolved.code == "config.conflict-resolved"
    assert 'it took "Tu es testé.", over the changes' in resolved.problem


def test_config_get_names_every_file_and_every_value_an_edit_leaves(
    theatre: Path, tmp_path: Path
) -> None:
    fields = (WORKSPACE, ("actors", "tester", "onContextFull"))
    checker = (("actors", "checker"), TESTER)
    _conflicted(
        theatre,
        tmp_path,
        tuple((f, v) for f, v in zip(fields, ("theatre", "fail"), strict=True)),
        tuple((f, v) for f, v in zip(fields, ("worktree", "compact"), strict=True)),
        also=(checker,),
    )
    _append(theatre, " Still.", MD)
    _append(theatre, " Still.", "actors/checker.md")
    (notice,) = _sync(theatre, query=True).notices
    assert notice.problem == (
        "Edits to .troupe/actors/checker.md, .troupe/actors/tester.md aren't recorded yet: config "
        "has conflicts, and they leave actors.tester.onContextFull, actors.tester.workspace "
        "unresolved."
    )


# Forcing past a file troupe can't read


def test_force_replaces_a_file_that_breaks_a_rule_and_keeps_it(theatre: Path) -> None:
    _tester(theatre)
    _append(theatre, "workspace: nowhere")
    broken = _file(theatre).read_bytes()
    with pytest.raises(TroupeError) as caught:
        _sync(theatre)
    assert caught.value.code == "config.file-invalid"
    synced = _sync(theatre, force=True)
    assert synced.edits == ()
    assert len(_events(theatre)) == 1
    assert [(a.path, a.action, a.forced) for a in synced.actions] == [(YAML, "write", True)]
    assert list(synced.kept) == [YAML]
    assert "nowhere" not in _file(theatre).read_text("utf-8")
    assert file_notices(synced) == []
    assert broken != _file(theatre).read_bytes()


def test_force_with_a_change_records_the_change_and_replaces_the_file(theatre: Path) -> None:
    _tester(theatre)
    _append(theatre, "workspace: nowhere")
    synced = _sync(theatre, (("actors", "tester", "character"), "Hi."), force=True)
    assert synced.change is not None
    assert synced.own == frozenset({MD})
    assert list(synced.kept) == [YAML]
    assert _file(theatre, MD).read_text("utf-8") == "Hi."
