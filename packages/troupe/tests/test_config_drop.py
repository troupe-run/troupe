"""Dropping or keeping an abandoned edit through the client protocol (spec: config-hand-edits, "A
person drops or keeps an abandoned edit"; client-protocol, "Config drop and keep are protocol
commands"; abandoned-edits design D6, D7)."""

import asyncio
from pathlib import Path
from typing import Any

import pytest

from client_schemas import check
from configtesting import TESTER
from gitrepo import Repo, make_repo
from protocol_schemas import validator_for
from runtesting import INIT, OK, Harness, request, script
from storetesting import ADA, git_service, snapshot
from troupe.core.client import messages as m
from troupe.core.client.dispatch import call
from troupe.core.client.session import Session
from troupe.core.config import aggregate
from troupe.core.config.abandoned import KEPT
from troupe.core.errors import TroupeError
from troupe.core.runs.perform import perform

TESTER_YAML = ".troupe/actors/tester.yaml"


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    made = make_repo(tmp_path, "theatre")
    (made.path / ".troupe").mkdir()
    return made


def _call(repo: Repo, method: str, params: dict[str, Any]) -> Any:  # noqa: ANN401
    session = Session(theatre=repo.path, env=dict(ADA))
    return asyncio.run(call(method, params, session, lambda _: None))


def _refused(repo: Repo, method: str, params: dict[str, Any]) -> TroupeError:
    with pytest.raises(TroupeError) as raised:
        _call(repo, method, params)
    validator_for("https://troupe.run/protocol/error.schema.json").validate(raised.value.to_data())
    return raised.value


def _replace(repo: Repo, relative: str, old: str, new: str) -> None:
    path = repo.path / relative
    text = path.read_text("utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


def _segments(repo: Repo) -> list[str]:
    events = repo.path / ".troupe" / "events"
    return sorted(p.relative_to(repo.path).as_posix() for p in events.glob("*.jsonl"))


def _tracked(repo: Repo) -> dict[str, str]:
    """Every file under .troupe/ but the clone-local ones, with a hash of its bytes."""
    return {k: v for k, v in snapshot(repo.path / ".troupe").items() if not k.startswith("local/")}


def _abandon(repo: Repo, old: str = "out/hello.txt", new: str = "out/a.txt") -> str:
    """Edit the tester's file, sync, restore it and sync: the closing change id."""
    _replace(repo, TESTER_YAML, old, new)
    _call(repo, "sync", {})
    repo.git("restore", TESTER_YAML)
    change: str = _call(repo, "sync", {})["edits"][0]["change"]
    return change


def _started(repo: Repo) -> list[str]:
    """A theatre with the tester, committed; the segments it has."""
    _call(repo, "config-set", {"operations": [{"path": ["actors", "tester"], "value": TESTER}]})
    repo.commit_all("tester")
    return _segments(repo)


# Requirement: A person drops or keeps an abandoned edit


def test_dropping_removes_both_syncs_event_files_and_leaves_config_as_before(repo: Repo) -> None:
    committed = _started(repo)
    config_before = git_service(repo).history(aggregate.STREAM)
    file_before = (repo.path / TESTER_YAML).read_bytes()
    closing = _abandon(repo)
    added = sorted(set(_segments(repo)) - set(committed))

    result = _call(repo, "config-drop", {"change": closing})

    check(result, "config-drop-result.schema.json")
    assert sorted(result["segments"]) == added
    assert len(result["changes"]) == 2
    assert result["rehearsed"] is False
    assert _segments(repo) == committed
    assert [r.id for r in git_service(repo).history(aggregate.STREAM)] == [
        r.id for r in config_before
    ]
    assert (repo.path / TESTER_YAML).read_bytes() == file_before
    assert "?? .troupe/events" not in repo.git("status", "--porcelain")
    before = _tracked(repo)
    after_sync = _call(repo, "sync", {})
    assert after_sync["edits"] == []
    assert _tracked(repo) == before  # the next sync records nothing and writes nothing


def test_rehearsing_a_drop_names_what_it_would_remove_and_removes_nothing(repo: Repo) -> None:
    _started(repo)
    closing = _abandon(repo)
    before = _segments(repo)
    result = _call(repo, "config-drop", {"change": closing, "rehearse": True})
    check(result, "config-drop-result.schema.json")
    assert result["rehearsed"] is True
    assert len(result["segments"]) == 2
    assert set(result["segments"]) <= set(before)
    assert _segments(repo) == before


def test_a_drop_no_longer_safe_after_a_run_is_refused_naming_the_run(tmp_path: Path) -> None:
    harness = Harness(make_repo(tmp_path, "theatre"))
    (harness.repo.path / ".troupe").mkdir()
    harness.configure(request(script(INIT, OK)))
    harness.repo.commit_all("tester")
    closing = _abandon(harness.repo, "workspace: theatre", "workspace: worktree")
    before = _segments(harness.repo)
    parsed = m.PerformRequest.from_data({"actor": "tester", "direction": "go"})
    result = asyncio.run(
        perform(parsed, harness.session(), harness.send, backends=harness.backends())
    )
    assert result.run is not None

    error = _refused(harness.repo, "config-drop", {"change": closing})

    assert error.code == "config.round-trip-kept"
    assert error.details["reason"] == "run"
    assert error.details["blocker"] == result.run.run_id
    assert set(before) <= set(_segments(harness.repo))


def test_a_change_that_closed_no_round_trip_is_refused(repo: Repo) -> None:
    _started(repo)
    change = _call(
        repo,
        "config-set",
        {"operations": [{"path": ["actors", "tester", "workspace"], "value": "theatre"}]},
    )["change"]
    for method in ("config-drop", "config-keep"):
        error = _refused(repo, method, {"change": change})
        assert error.code == "config.no-round-trip"
        assert error.details == {"change": change}


def test_keeping_stops_sync_asking_and_keeps_the_changes(repo: Repo) -> None:
    _started(repo)
    closing = _abandon(repo)
    before = _segments(repo)
    result = _call(repo, "config-keep", {"change": closing})
    check(result, "config-keep-result.schema.json")
    again = _call(repo, "sync", {})
    assert [n for n in again["notices"] if n["code"] == "config.edit-abandoned"] == []
    assert _segments(repo) == before


def test_a_keep_lives_in_this_clone_only(repo: Repo) -> None:
    _started(repo)
    closing = _abandon(repo)
    repo.commit_all("events")  # so the keep record would be the only new file git could see
    _call(repo, "config-keep", {"change": closing})
    assert (repo.path / ".troupe" / KEPT).is_file()
    assert repo.git("status", "--porcelain") == ""


def test_rehearsing_a_keep_writes_nothing(repo: Repo) -> None:
    _started(repo)
    closing = _abandon(repo)
    result = _call(repo, "config-keep", {"change": closing, "rehearse": True})
    assert result["rehearsed"] is True
    assert not (repo.path / ".troupe" / KEPT).exists()


def test_dropping_a_kept_round_trip_drops_it_and_forgets_the_keep(repo: Repo) -> None:
    _started(repo)
    closing = _abandon(repo)
    _call(repo, "config-keep", {"change": closing})
    _call(repo, "config-drop", {"change": closing})
    assert (repo.path / ".troupe" / KEPT).read_bytes() == b"[]\n"


# Requirement: Config drop and keep are protocol commands


def test_a_drop_request_naming_segments_is_refused_naming_the_field(repo: Repo) -> None:
    _started(repo)
    closing = _abandon(repo)
    error = _refused(repo, "config-drop", {"change": closing, "segments": ["x"]})
    assert error.code == "client.invalid-request"
    assert "segments" in error.problem
