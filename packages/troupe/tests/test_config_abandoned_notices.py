"""Commands report abandoned edits, and sync asks again while one can be dropped (spec:
config-hand-edits, "An edit undone by hand is reported as abandoned", "An abandoned edit that
can't be dropped says why", "Sync asks again while a drop is possible"; abandoned-edits design
D5, D7). Through the client protocol, in a real git theatre."""

import asyncio
from pathlib import Path
from typing import Any

import pytest

from configtesting import TESTER
from gitrepo import Repo, make_repo
from protocol_schemas import check_notice
from runtesting import INIT, OK, Harness, request, script
from storetesting import ADA
from troupe.core.client import messages as m
from troupe.core.client.dispatch import call
from troupe.core.client.session import Session
from troupe.core.config.abandoned import KEPT
from troupe.core.runs.perform import perform

TESTER_YAML = ".troupe/actors/tester.yaml"
TESTER_MD = ".troupe/actors/tester.md"
ABANDONED = "config.edit-abandoned"


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    made = make_repo(tmp_path, "theatre")
    (made.path / ".troupe").mkdir()
    return made


def _call(repo: Repo, method: str, params: dict[str, Any]) -> Any:  # noqa: ANN401
    session = Session(theatre=repo.path, env=dict(ADA))
    return asyncio.run(call(method, params, session, lambda _: None))


def _set(repo: Repo, path: list[str], value: object) -> Any:  # noqa: ANN401
    return _call(repo, "config-set", {"operations": [{"path": path, "value": value}]})


def _sync(repo: Repo) -> dict[str, Any]:
    result: dict[str, Any] = _call(repo, "sync", {})
    return result


def _abandoned(result: dict[str, Any]) -> list[dict[str, Any]]:
    found = [n for n in result["notices"] if n["code"] == ABANDONED]
    for notice in found:
        check_notice(notice)
    return found


def _replace(repo: Repo, relative: str, old: str, new: str) -> None:
    path = repo.path / relative
    text = path.read_text("utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


def _started(repo: Repo) -> None:
    _set(repo, ["actors", "tester"], TESTER)
    repo.commit_all("tester")


def _edited(repo: Repo) -> str:
    """Edit the tester's file and sync; the change id recorded."""
    _replace(repo, TESTER_YAML, "out/hello.txt", "out/a.txt")
    change: str = _sync(repo)["edits"][0]["change"]
    return change


# Requirement: An edit undone by hand is reported as abandoned


def test_an_edit_undone_with_git_restore_is_reported_as_droppable(repo: Repo) -> None:
    _started(repo)
    first = _edited(repo)
    repo.git("restore", TESTER_YAML)
    result = _sync(repo)
    closing = result["edits"][0]["change"]

    [notice] = _abandoned(result)

    assert notice["details"] == {
        "change": closing,
        "files": [TESTER_YAML],
        "changes": [first, closing],
        "droppable": True,
    }
    assert f"troupe config drop {closing}" in notice["fix"]
    assert f"troupe config keep {closing}" in notice["fix"]


def test_back_with_a_comment_the_original_didnt_have_is_reported(repo: Repo) -> None:
    _started(repo)
    _edited(repo)
    _replace(repo, TESTER_YAML, "out/a.txt", "out/hello.txt  # as it was")
    assert len(_abandoned(_sync(repo))) == 1


def test_several_steps_undone_are_named_together(repo: Repo) -> None:
    _started(repo)
    one = _edited(repo)
    _replace(repo, TESTER_YAML, "out/a.txt", "out/b.txt")
    two = _sync(repo)["edits"][0]["change"]
    repo.git("restore", TESTER_YAML)
    result = _sync(repo)
    [notice] = _abandoned(result)
    assert notice["details"]["changes"] == [one, two, result["edits"][0]["change"]]


def test_a_partial_undo_is_not_reported(repo: Repo) -> None:
    _started(repo)
    _replace(repo, TESTER_YAML, "out/hello.txt", "out/a.txt\nworkspace: theatre")
    _sync(repo)
    _replace(repo, TESTER_YAML, "out/a.txt", "out/hello.txt")
    assert _abandoned(_sync(repo)) == []


def test_a_config_set_undone_by_git_restore_is_reported(repo: Repo) -> None:
    _started(repo)
    set_change = _set(repo, ["actors", "tester", "workspace"], "theatre")["change"]
    repo.git("restore", TESTER_YAML)
    [notice] = _abandoned(_sync(repo))
    assert notice["details"]["changes"][0] == set_change


def test_only_the_latest_round_trip_is_named(repo: Repo) -> None:
    _started(repo)
    _edited(repo)
    _replace(repo, TESTER_YAML, "out/a.txt", "out/hello.txt")
    _sync(repo)
    third = _edited(repo)
    repo.git("restore", TESTER_YAML)
    result = _sync(repo)
    [notice] = _abandoned(result)
    assert notice["details"]["changes"] == [third, result["edits"][0]["change"]]


def test_a_stash_is_reported_like_any_restore(repo: Repo) -> None:
    _started(repo)
    _edited(repo)
    repo.git("stash", "push", "-q", "--", TESTER_YAML)
    assert len(_abandoned(_sync(repo))) == 1


def test_a_deleted_actor_restored_is_one_notice_naming_both_files(repo: Repo) -> None:
    _started(repo)
    (repo.path / TESTER_YAML).unlink()
    (repo.path / TESTER_MD).unlink()
    removal = _sync(repo)["edits"][0]["change"]
    repo.git("restore", TESTER_YAML, TESTER_MD)
    result = _sync(repo)
    [notice] = _abandoned(result)
    assert notice["details"]["files"] == [TESTER_MD, TESTER_YAML]
    assert notice["details"]["changes"] == [removal, result["edits"][0]["change"]]


# Requirement: An abandoned edit that can't be dropped says why


def _harness(tmp_path: Path) -> Harness:
    harness = Harness(make_repo(tmp_path, "theatre"))
    (harness.repo.path / ".troupe").mkdir()
    harness.configure(request(script(INIT, OK)))
    harness.repo.commit_all("tester")
    return harness


def _perform(harness: Harness) -> m.PerformResult:
    parsed = m.PerformRequest.from_data({"actor": "tester", "direction": "go"})
    return asyncio.run(
        perform(parsed, harness.session(), harness.send, backends=harness.backends())
    )


def test_a_run_that_used_the_edit_keeps_it_naming_the_run(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    _replace(harness.repo, TESTER_YAML, "workspace: theatre", "workspace: worktree")
    result = _perform(harness)
    assert result.run is not None
    harness.repo.git("restore", TESTER_YAML)
    [notice] = _abandoned(_sync(harness.repo))
    assert notice["details"]["droppable"] is False
    assert notice["details"]["reason"] == "run"
    assert notice["details"]["blocker"] == result.run.run_id
    assert result.run.run_id in notice["problem"]


def test_restored_then_performed_is_kept_before_the_run_starts(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    _replace(harness.repo, TESTER_YAML, "workspace: theatre", "workspace: worktree")
    _sync(harness.repo)
    harness.repo.git("restore", TESTER_YAML)
    _perform(harness)
    order = [
        u.get("notice", {}).get("code") or ("run" if "runId" in u else None)
        for u in harness.updates
    ]
    notices = [u["notice"] for u in harness.updates if u.get("notice", {}).get("code") == ABANDONED]
    [notice] = notices
    check_notice(notice)
    assert notice["details"]["reason"] == "run"
    assert "blocker" not in notice["details"]
    assert order.index(ABANDONED) < order.index("run")  # reported before the run starts


def test_committed_changes_are_kept(repo: Repo) -> None:
    _started(repo)
    _edited(repo)
    repo.commit_all("the edit")
    _replace(repo, TESTER_YAML, "out/a.txt", "out/hello.txt")
    [notice] = _abandoned(_sync(repo))
    assert notice["details"]["reason"] == "committed"


def test_a_config_set_with_the_edit_back_builds_on_it(repo: Repo) -> None:
    _started(repo)
    _edited(repo)
    repo.git("restore", TESTER_YAML)
    result = _set(repo, ["actors", "tester", "onContextFull"], "compact")
    [notice] = _abandoned(result)
    assert notice["details"]["reason"] == "built-on"
    assert notice["details"]["blocker"] == result["change"]


def test_another_file_changed_in_between_is_named(repo: Repo) -> None:
    _started(repo)
    _set(repo, ["actors", "reviewer"], TESTER)
    repo.commit_all("reviewer")
    _edited(repo)
    _replace(repo, ".troupe/actors/reviewer.yaml", "out/hello.txt", "out/a.txt")
    reviewer = _sync(repo)["edits"][0]["change"]
    repo.git("restore", TESTER_YAML)
    [notice] = _abandoned(_sync(repo))
    assert notice["details"]["reason"] == "changes-more"
    assert notice["details"]["blocker"] == reviewer


# Requirement: Sync asks again while a drop is possible


def _droppable(repo: Repo) -> str:
    _started(repo)
    _edited(repo)
    repo.git("restore", TESTER_YAML)
    result = _sync(repo)
    [notice] = _abandoned(result)
    assert notice["details"]["droppable"] is True
    change: str = notice["details"]["change"]
    return change


def test_sync_asks_again_when_there_is_no_answer(repo: Repo) -> None:
    closing = _droppable(repo)
    again = _sync(repo)
    assert again["edits"] == []
    [notice] = _abandoned(again)
    assert notice["details"]["change"] == closing


def test_config_get_doesnt_ask_again(repo: Repo) -> None:
    _droppable(repo)
    assert _abandoned(_call(repo, "config-get", {})) == []


def test_sync_stops_asking_once_the_events_are_committed(repo: Repo) -> None:
    _droppable(repo)
    repo.commit_all("events")
    assert _abandoned(_sync(repo)) == []


def test_sync_stops_asking_once_kept(repo: Repo) -> None:
    closing = _droppable(repo)
    (repo.path / ".troupe" / KEPT).parent.mkdir(parents=True, exist_ok=True)
    (repo.path / ".troupe" / KEPT).write_text(f'["{closing}"]\n', encoding="utf-8")
    assert _abandoned(_sync(repo)) == []


def test_an_unreadable_keep_record_is_named_and_the_question_comes_back(repo: Repo) -> None:
    _droppable(repo)
    (repo.path / ".troupe" / KEPT).parent.mkdir(parents=True, exist_ok=True)
    (repo.path / ".troupe" / KEPT).write_bytes(b"not json")
    result = _sync(repo)
    codes = [n["code"] for n in result["notices"]]
    assert "config.kept-unreadable" in codes
    assert len(_abandoned(result)) == 1
