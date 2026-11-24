"""What test_cli_runs.py and test_cli_runs_unit.py share."""

import io
import json
from pathlib import Path
from typing import Any

import pytest

from gitrepo import Repo
from runtesting import ADA, ALLOW, theatre
from troupe.cli import main


def cli(*argv: str) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(list(argv), stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


@pytest.fixture(name="repo")
def repo_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Repo:
    """A git theatre as the working directory, with ada acting and the local stage allowed."""
    made = theatre(tmp_path)
    for name, value in {**made.env, **ADA, **ALLOW}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.chdir(made.path)
    return made


def configure(
    repo: Repo,
    options: dict[str, Any],
    *,
    expect: list[str] | None = None,
    name: str = "actor.json",
    workspace: str = "theatre",
    effects: dict[str, list[str]] | None = None,
) -> None:
    """Define the actor tester in config through the CLI, as a person would, working in the
    theatre unless ``workspace`` says otherwise."""
    actor = {
        "runner": "scripted",
        "options": options,
        "expect": expect or [],
        "effects": effects if effects is not None else {"write": list(expect or [])},
        "workspace": workspace,
    }
    (repo.path / name).write_text(json.dumps(actor), encoding="utf-8")
    code, _, err = cli("config", "set", f"actors.tester=@{name}")
    assert code == 0, err
