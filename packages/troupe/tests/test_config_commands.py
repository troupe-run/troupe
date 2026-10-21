"""config-set, config-get and flush through the dispatcher, against a real git theatre (spec:
config, config-files, client-protocol; config-model design D9, D10)."""

import asyncio
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from client_schemas import MESSAGES, is_valid
from configtesting import TESTER
from gitrepo import Repo
from protocol_schemas import check_error
from runtesting import ADA, theatre
from storetesting import git_service
from troupe.core.client.dispatch import call
from troupe.core.client.session import Session
from troupe.core.config import aggregate, projection
from troupe.core.config.kinds import staged_name
from troupe.core.errors import TroupeError

TESTER_PATH = ["actors", "tester"]


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return theatre(tmp_path)


def _call(repo: Repo, method: str, params: dict[str, Any], updates: list[Any] | None = None) -> Any:  # noqa: ANN401
    session = Session(theatre=repo.path, env=dict(ADA))
    collected = updates if updates is not None else []
    result = asyncio.run(call(method, params, session, collected.append))
    assert is_valid(params, MESSAGES[method]["request"])
    assert is_valid(result, MESSAGES[method]["result"]), result
    for update in collected:
        assert is_valid(update, MESSAGES[method]["update"]), update
    return result


def _set(repo: Repo, *operations: tuple[list[str], Any], **extra: Any) -> Any:  # noqa: ANN401
    ops = [
        {"path": path, "unset": True} if value is ... else {"path": path, "value": value}
        for path, value in operations
    ]
    return _call(repo, "config-set", {"operations": ops, **extra})


def _events(repo: Repo) -> list[Any]:
    return git_service(repo).history(aggregate.STREAM)


def _actor_file(repo: Repo) -> Path:
    return repo.path / ".troupe" / "actors" / "tester.yaml"


# config-set


def test_setting_an_actor_records_one_change_and_writes_its_files(repo: Repo) -> None:
    result = _set(repo, (TESTER_PATH, TESTER), reason="the first actor")
    [event] = _events(repo)
    assert event.lineage is not None
    assert event.lineage["change"] == result["change"]
    assert event.lineage["reason"] == "the first actor"
    assert {f["path"] for f in result["files"]} == {
        ".troupe/actors/tester.yaml",
        ".troupe/actors/tester.md",
    }
    assert (
        _actor_file(repo).read_bytes()
        == projection.render({"actors": {"tester": TESTER}})["actors/tester.yaml"]
    )
    assert (repo.path / ".troupe" / "actors" / "tester.md").read_text("utf-8") == TESTER[
        "character"
    ]
    assert not list((repo.path / ".troupe" / "actors").glob(".*.troupe~"))


def test_the_files_a_change_writes_are_recorded_with_their_hashes(repo: Repo) -> None:
    _set(repo, (TESTER_PATH, TESTER))
    [event] = _events(repo)
    import json

    files = json.loads(event.state)["files"]
    assert {f["path"]: f["hash"] for f in files} == {
        path: projection.file_hash(data)
        for path, data in projection.render({"actors": {"tester": TESTER}}).items()
    }


def test_setting_a_value_to_what_it_is_records_nothing(repo: Repo) -> None:
    _set(repo, (TESTER_PATH, TESTER))
    result = _set(repo, (["actors", "tester", "runner"], "scripted"))
    assert "change" not in result
    assert result["entries"] == []
    assert len(_events(repo)) == 1


def test_unsetting_an_actor_removes_its_files(repo: Repo) -> None:
    _set(repo, (TESTER_PATH, TESTER))
    _set(repo, (TESTER_PATH, ...))
    assert not (repo.path / ".troupe" / "actors").exists()
    assert len(_events(repo)) == 2


@pytest.mark.parametrize(
    "operations",
    [
        pytest.param([(TESTER_PATH, {**TESTER, "runnr": "x"})], id="a misspelt field"),
        pytest.param(
            [(TESTER_PATH, {**TESTER, "options": {**TESTER["options"], "speed": 2}})],
            id="an option the runner doesn't define",
        ),
        pytest.param(
            [(TESTER_PATH, {k: v for k, v in TESTER.items() if k != "expect"})],
            id="no effect check",
        ),
        pytest.param([(TESTER_PATH, {**TESTER, "expect": ["../x"]})], id="a path outside"),
        pytest.param([(["actors", "Tester"], TESTER)], id="a bad actor name"),
    ],
)
def test_a_refused_change_records_nothing_and_writes_no_file(
    repo: Repo, operations: list[tuple[list[str], Any]]
) -> None:
    with pytest.raises(TroupeError) as caught:
        _set(repo, *operations)
    assert caught.value.code == "config.invalid"
    check_error(caught.value.to_data())
    assert _events(repo) == []
    assert not (repo.path / ".troupe" / "actors").exists()


def test_a_change_over_a_hand_edited_file_is_refused_and_records_nothing(repo: Repo) -> None:
    _set(repo, (TESTER_PATH, TESTER))
    _actor_file(repo).write_text("# mine\n", encoding="utf-8")
    with pytest.raises(TroupeError) as caught:
        _set(repo, (["actors", "tester", "expect"], []))
    assert caught.value.code == "config.file-not-troupes"
    assert len(_events(repo)) == 1
    assert _actor_file(repo).read_text("utf-8") == "# mine\n"


def test_rehearsing_a_change_shows_it_and_records_and_writes_nothing(repo: Repo) -> None:
    result = _set(repo, (TESTER_PATH, TESTER), rehearse=True)
    assert "change" not in result
    assert result["entries"]
    assert {f["action"] for f in result["files"]} == {"write"}
    assert _events(repo) == []
    assert not (repo.path / ".troupe" / "actors").exists()


def test_a_crash_after_recording_is_finished_by_the_next_flush(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    from troupe.core.config import commands

    calls: list[object] = []
    real = projection.execute

    def crash(*args: Any) -> dict[str, str]:  # noqa: ANN401
        calls.append(args)
        if len(calls) == 2:  # the first is the flush before the change; the second moves its files
            raise KeyboardInterrupt  # troupe stopped between recording and moving the files
        return real(*args)

    monkeypatch.setattr(commands, "execute", crash)
    with pytest.raises(KeyboardInterrupt):
        _set(repo, (TESTER_PATH, TESTER))
    monkeypatch.undo()
    assert len(_events(repo)) == 1
    assert (repo.path / ".troupe" / staged_name("actors/tester.yaml")).exists()
    assert not _actor_file(repo).exists()
    result = _call(repo, "flush", {})
    assert {(f["path"], f["action"]) for f in result["files"]} >= {
        (".troupe/actors/.tester.yaml.troupe~", "finish")
    }
    assert _actor_file(repo).exists()
    assert not (repo.path / ".troupe" / staged_name("actors/tester.yaml")).exists()


def test_a_wait_for_another_command_writing_config_is_announced(repo: Repo) -> None:
    holder = textwrap.dedent(
        f"""
        import time
        from pathlib import Path
        from troupe.core.config.projection import locked
        with locked(Path({str(repo.path / ".troupe")!r})):
            print("held", flush=True)
            time.sleep(2.5)
        """
    )
    child = subprocess.Popen([sys.executable, "-c", holder], stdout=subprocess.PIPE, text=True)
    updates: list[Any] = []
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "held"
        _call(
            repo,
            "config-set",
            {"operations": [{"path": TESTER_PATH, "value": TESTER}]},
            updates,
        )
    finally:
        child.wait(timeout=30)
    assert any(u["notice"]["code"] == "config.waiting" for u in updates)


# config-get


def test_config_get_shows_the_whole_config_or_the_value_at_a_path(repo: Repo) -> None:
    _set(repo, (TESTER_PATH, TESTER))
    whole = _call(repo, "config-get", {})
    assert whole["value"] == {"actors": {"tester": TESTER}}
    assert len(whole["heads"]) == 1
    runner = _call(repo, "config-get", {"path": ["actors", "tester", "runner"]})
    assert runner["value"] == "scripted"
    nothing = _call(repo, "config-get", {"path": ["actors", "nobody"]})
    assert "value" not in nothing


def test_config_get_in_a_theatre_with_no_config_has_no_value_and_no_heads(repo: Repo) -> None:
    result = _call(repo, "config-get", {})
    assert "value" not in result
    assert result["heads"] == []


# flush


def test_flush_writes_a_deleted_file_again_with_a_notice(repo: Repo) -> None:
    _set(repo, (TESTER_PATH, TESTER))
    _actor_file(repo).unlink()
    result = _call(repo, "flush", {})
    assert _actor_file(repo).exists()
    assert [n["code"] for n in result["notices"]] == ["config.file-rewritten"]


def test_flush_rehearsed_reports_and_writes_nothing(repo: Repo) -> None:
    _set(repo, (TESTER_PATH, TESTER))
    _actor_file(repo).unlink()
    result = _call(repo, "flush", {"rehearse": True})
    assert [f["action"] for f in result["files"]] == ["write"]
    assert not _actor_file(repo).exists()


def test_flush_forced_past_a_hand_edit_names_where_the_edit_was_kept(repo: Repo) -> None:
    _set(repo, (TESTER_PATH, TESTER))
    _actor_file(repo).write_text("# mine\n", encoding="utf-8")
    result = _call(repo, "flush", {"force": True})
    [forced] = [f for f in result["files"] if "kept" in f]
    assert forced["kept"] == projection.file_hash(b"# mine\n")
