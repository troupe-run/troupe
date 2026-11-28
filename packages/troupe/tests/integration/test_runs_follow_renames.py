"""Runs follow a rename: status and logs show the name a run's actor has now, and perform names it
for the old name (spec: cli, "Status and logs show an actor's current name", "Perform names the
new name of a renamed actor"; config-mv design D4)."""

import io
import json
from pathlib import Path
from typing import Any

import pytest

from client_schemas import check
from gitrepo import Repo, make_repo
from runtesting import ADA, ALLOW, succeeded_run
from troupe.cli import main
from troupe.core.errors import TroupeError
from troupe.core.exit_codes import ExitCode


def cli(*argv: str) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(list(argv), stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Repo:
    made = make_repo(tmp_path, "theatre")
    for name, value in {**made.env, **ADA, **ALLOW}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.chdir(made.path)
    code, _, err = cli("init", "--audition", "--runner", "scripted")
    assert code == ExitCode.OK, err
    made.commit_all("Add a troupe theatre")
    return made


def _performed() -> str:
    # The audition's actor waits at its gate for director (manual-gates decision 8).
    code, out, err = cli("perform", "lead", "--direction", "Write the file.")
    assert code == ExitCode.WAITING, err
    return succeeded_run(out)


def _status_json() -> dict[str, Any]:
    code, out, err = cli("status", "--json")
    assert code == ExitCode.OK, err
    result = json.loads(out)
    assert isinstance(result, dict)
    return result


# Requirement: Status and logs show an actor's current name


def test_status_shows_a_run_before_a_rename_as_the_old_name_now_the_new(repo: Repo) -> None:
    run = _performed()
    code, _, err = cli("config", "mv", "actors.lead", "actors.star")
    assert code == ExitCode.OK, err
    code, out, _ = cli("status")
    assert code == ExitCode.OK
    [line] = [line for line in out.splitlines() if f"  run {run[:8]}  " in line]
    assert "lead (now star)" in line
    result = _status_json()
    check(result, "status-result.schema.json")
    [summary] = result["runs"]
    assert summary["actor"] == "lead"
    assert summary["actorNow"] == "star"


def test_logs_follow_a_chain_of_renames_to_the_name_now(repo: Repo) -> None:
    run = _performed()
    cli("config", "mv", "actors.lead", "actors.star")
    cli("config", "mv", "actors.star", "actors.checker")
    code, out, err = cli("logs", run)
    assert code == ExitCode.OK, err
    assert "  actor: lead (now checker)" in out.splitlines()


def test_a_run_whose_actor_kept_its_name_shows_the_name_alone(repo: Repo) -> None:
    run = _performed()
    code, out, _ = cli("logs", run)
    assert code == ExitCode.OK
    assert not any(line.startswith("  actor:") for line in out.splitlines())
    code, out, _ = cli("status")
    [line] = [line for line in out.splitlines() if f"  run {run[:8]}  " in line]
    assert " lead " in line
    assert "(now" not in line
    assert "actorNow" not in _status_json()["runs"][0]


def test_a_run_whose_actor_was_removed_since_shows_the_name_alone(repo: Repo) -> None:
    run = _performed()
    code, _, err = cli("config", "unset", "actors.lead")
    assert code == ExitCode.OK, err
    code, out, _ = cli("logs", run)
    assert code == ExitCode.OK
    assert not any(line.startswith("  actor:") for line in out.splitlines())
    assert "actorNow" not in _status_json()["runs"][0]


# Requirement: Perform names the new name of a renamed actor


def test_performing_the_old_name_is_refused_naming_the_new_one(repo: Repo) -> None:
    cli("config", "mv", "actors.lead", "actors.star")
    code, _, err = cli("perform", "lead", "--direction", "Write the file.")
    assert code != ExitCode.OK
    assert "Config has no actor named 'lead' (it has: star)." in err
    assert "fix: lead was renamed star: troupe perform star." in err


def test_an_old_name_follows_a_chain_of_renames_in_perform_s_fix(repo: Repo) -> None:
    from storetesting import git_service
    from troupe.core.config.stream import read
    from troupe.core.runs.perform import _from_config

    cli("config", "mv", "actors.lead", "actors.star")
    cli("config", "mv", "actors.star", "actors.checker")
    with pytest.raises(TroupeError) as caught:
        _from_config(read(git_service(repo)), "lead")
    assert caught.value.details["renamedTo"] == "checker"


def test_status_still_shows_runs_when_configs_stream_cant_be_read(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    from troupe.core.config import stream

    run = _performed()
    cli("config", "mv", "actors.lead", "actors.star")

    def broken(store: object) -> object:
        raise TroupeError(
            "events.missing-parent",
            problem="A config event follows one that isn't here.",
            fix="Restore the file that held it.",
            details={
                "line": 1,
                "event": "sha256:" + "1" * 64,
                "missingParent": "sha256:" + "0" * 64,
                "onlyIn": [],
            },
        )

    monkeypatch.setattr(stream, "read", broken)
    code, out, err = cli("status")
    assert code == ExitCode.OK, err
    [line] = [line for line in out.splitlines() if f"  run {run[:8]}  " in line]
    assert " lead " in line
    assert "(now" not in line
