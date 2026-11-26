"""Abandoned edits on the command line, end to end in a real git theatre (spec: cli, "Config and
sync commands"; config-hand-edits; abandoned-edits design D8, tasks 4.3 and 6.1)."""

import io
import re
from pathlib import Path

import pytest

from gitrepo import Repo, make_repo
from runtesting import ADA, ALLOW
from troupe.cli import main
from troupe.core.exit_codes import ExitCode

LEAD_YAML = ".troupe/actors/lead.yaml"
DROP = re.compile(r"troupe config drop ([0-9A-HJKMNP-TV-Z]{26})")


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


def _untracked_events(repo: Repo) -> list[str]:
    return [
        line
        for line in repo.git("status", "--porcelain", "--untracked-files=all").splitlines()
        if line.startswith("?? .troupe/events/")
    ]


def _abandon(repo: Repo) -> str:
    """Edit the lead's file, sync, restore it and sync: the change id the notice names."""
    path = repo.path / LEAD_YAML
    path.write_text(path.read_text("utf-8") + "onContextFull: compact\n", encoding="utf-8")
    code, _, err = cli("sync")
    assert code == ExitCode.OK, err
    repo.git("restore", LEAD_YAML)
    code, _, err = cli("sync")
    assert code == ExitCode.OK, err
    found = DROP.search(err)
    assert found is not None, err
    return found.group(1)


def test_an_abandoned_edit_dropped_end_to_end(repo: Repo) -> None:
    change = _abandon(repo)
    assert len(_untracked_events(repo)) == 2

    code, out, err = cli("config", "drop", change)

    assert code == ExitCode.OK, err
    assert out.startswith("Dropped 2 changes (")
    assert out.count(".troupe/events/") == 2
    assert _untracked_events(repo) == []
    code, out, err = cli("sync")
    assert code == ExitCode.OK, err
    assert out == "Nothing to do: the config files are what config says.\n"
    assert "config drop" not in err


def test_a_rehearsed_drop_exits_with_would_change_and_removes_nothing(repo: Repo) -> None:
    change = _abandon(repo)
    code, out, err = cli("config", "drop", change, "--rehearse")
    assert code == ExitCode.WOULD_CHANGE, err
    assert out.startswith("Would drop 2 changes (")
    assert len(_untracked_events(repo)) == 2


def test_keeping_says_so_and_sync_stops_asking(repo: Repo) -> None:
    change = _abandon(repo)
    code, out, err = cli("config", "keep", change)
    assert code == ExitCode.OK, err
    assert out == f"Kept the changes of {change}; troupe won't ask about them again.\n"
    code, _, err = cli("sync")
    assert code == ExitCode.OK, err
    assert "config drop" not in err
    assert len(_untracked_events(repo)) == 2


def test_a_refused_drop_exits_with_its_codes_exit_code(repo: Repo) -> None:
    change = _abandon(repo)
    repo.commit_all("the round trip")
    code, out, err = cli("config", "drop", change)
    assert code == ExitCode.FAILURE
    assert out == ""
    assert "committed" in err
