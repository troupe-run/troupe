"""Every command syncs first: hand edits recorded, then files written (spec: config-hand-edits,
"Every command that uses config sweeps first", "troupe's own writes are never read as edits", "A
sweep can be rehearsed"; config-files, "Force replaces a file and keeps a copy"; hand-edit-sweep
design D1, D9, D11)."""

import asyncio
from pathlib import Path
from typing import Any

import pytest

from configtesting import TESTER
from gitrepo import Repo, make_repo
from runtesting import INIT, OK, Harness, request, script
from storetesting import ADA, git_service, snapshot
from troupe.core import strict_json
from troupe.core.client import messages as m
from troupe.core.client.dispatch import call
from troupe.core.client.session import Session
from troupe.core.config import aggregate
from troupe.core.runs.perform import perform

TESTER_PATH = ["actors", "tester"]


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    made = make_repo(tmp_path, "theatre")
    (made.path / ".troupe").mkdir()
    return made


def _call(repo: Repo, method: str, params: dict[str, Any]) -> Any:  # noqa: ANN401
    session = Session(theatre=repo.path, env=dict(ADA))
    return asyncio.run(call(method, params, session, lambda _: None))


def _set(repo: Repo, path: list[str], value: object, **extra: Any) -> Any:  # noqa: ANN401
    return _call(repo, "config-set", {"operations": [{"path": path, "value": value}], **extra})


def _events(repo: Repo) -> list[Any]:
    return git_service(repo).history(aggregate.STREAM)


def _yaml(repo: Repo) -> Path:
    return repo.path / ".troupe" / "actors" / "tester.yaml"


def _formatted(repo: Repo) -> None:
    """The tester's file as a person formats it: comments, blank lines, their own order."""
    text = _yaml(repo).read_text("utf-8")
    _yaml(repo).write_text(
        "# the tester, by hand\n\n" + text + "\n# end of file\n", encoding="utf-8"
    )


def _edit(repo: Repo, line: str) -> None:
    _yaml(repo).write_text(_yaml(repo).read_text("utf-8") + line + "\n", encoding="utf-8")


# Requirement: Every command that uses config sweeps first


def test_config_get_shows_what_the_file_says_and_records_it(repo: Repo) -> None:
    _set(repo, TESTER_PATH, TESTER)
    _edit(repo, "workspace: theatre")
    result = _call(repo, "config-get", {"path": ["actors", "tester", "workspace"]})
    assert result["value"] == "theatre"
    *_, edit = _events(repo)
    assert edit.lineage["actor"] == {"kind": "unknown"}
    assert [n["code"] for n in result["notices"]] == ["config.hand-edit-recorded"]


def test_a_command_that_doesnt_use_config_doesnt_sweep(repo: Repo) -> None:
    _set(repo, TESTER_PATH, TESTER)
    _edit(repo, "workspace: theatre")
    _call(repo, "status", {})
    assert len(_events(repo)) == 1


def test_a_perform_rehearsal_uses_a_hand_edit_and_records_nothing(tmp_path: Path) -> None:
    harness = Harness(make_repo(tmp_path, "theatre"))
    (harness.repo.path / ".troupe").mkdir()
    asked = request(script(INIT, OK))
    harness.configure(asked)
    character = harness.repo.path / ".troupe" / "actors" / "tester.md"
    character.write_text("Edited by hand.", encoding="utf-8")  # a new file: adds the character
    before = len(git_service(harness.repo).history(aggregate.STREAM))
    parsed = m.PerformRequest.from_data({"actor": "tester", "rehearse": True})
    result = asyncio.run(
        perform(parsed, harness.session(), harness.send, backends=harness.backends())
    )
    assert result.rehearsal is not None
    assert result.rehearsal.character is not None
    assert result.rehearsal.character.length == len("Edited by hand.")
    assert len(git_service(harness.repo).history(aggregate.STREAM)) == before
    codes = [u.get("notice", {}).get("code") for u in harness.updates]
    assert "config.hand-edit-recorded" in codes


# Requirement: A sweep can be rehearsed


def test_a_rehearsed_config_set_shows_the_sweeps_edit_and_records_nothing(repo: Repo) -> None:
    _set(repo, TESTER_PATH, TESTER)
    _edit(repo, "workspace: theatre")
    before = snapshot(repo.path / ".troupe")
    result = _set(repo, ["actors", "tester", "onContextFull"], "compact", rehearse=True)
    [notice] = [n for n in result["notices"] if n["code"] == "config.hand-edit-recorded"]
    assert notice["details"]["rehearsal"] is True
    assert "would record" in notice["problem"]
    assert len(_events(repo)) == 1
    assert snapshot(repo.path / ".troupe") == before


# Requirement: Force replaces a file and keeps a copy


def test_force_replaces_an_invalid_file_keeping_a_copy_and_records_the_valid_edits(
    repo: Repo,
) -> None:
    _set(repo, TESTER_PATH, TESTER)
    _set(repo, ["actors", "reviewer"], {k: v for k, v in TESTER.items() if k != "character"})
    _edit(repo, "workspace: theatre")
    reviewer = repo.path / ".troupe" / "actors" / "reviewer.yaml"
    reviewer.write_bytes(b"")  # mid-save, or broken
    result = _call(repo, "sync", {"force": True})
    assert [e["path"] for e in result["edits"]] == [".troupe/actors/tester.yaml"]
    [forced] = [f for f in result["files"] if f.get("kept")]
    assert forced["path"] == ".troupe/actors/reviewer.yaml"
    assert reviewer.read_bytes() != b""
    *_, edit = _events(repo)
    assert edit.lineage["vcs"]["source"]["path"] == ".troupe/actors/tester.yaml"


# Requirement: troupe's own writes are never read as edits (no loop)


def test_every_command_run_twice_records_and_writes_nothing_the_second_time(repo: Repo) -> None:
    _set(repo, TESTER_PATH, TESTER)
    _formatted(repo)
    _edit(repo, "workspace: theatre")
    commands = [
        ("sync", {}),
        ("config-get", {}),
        (
            "config-set",
            {"operations": [{"path": ["actors", "tester", "onContextFull"], "value": "compact"}]},
        ),
    ]
    for method, params in commands:
        _call(repo, method, params)
        events = len(_events(repo))
        files = snapshot(repo.path / ".troupe")
        _call(repo, method, params)
        assert len(_events(repo)) == events, method
        assert snapshot(repo.path / ".troupe") == files, method
    text = _yaml(repo).read_text("utf-8")
    assert text.startswith("# the tester, by hand\n\n")  # the person's formatting survived it all
    assert text.rstrip().endswith("onContextFull: compact") or "onContextFull: compact\n" in text


def test_the_record_of_present_files_lists_the_config_files_after_a_sync(repo: Repo) -> None:
    _set(repo, TESTER_PATH, TESTER)
    record = strict_json.loads(
        (repo.path / ".troupe" / "local" / "config" / "present.json").read_bytes()
    )
    assert record == ["actors/tester.md", "actors/tester.yaml"]
