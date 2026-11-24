"""Helpers that test_cli_config_merges.py shares with other test modules."""

import io
import subprocess
from pathlib import Path

import pytest

from gitrepo import AUTHOR, Repo
from runtesting import ADA, ALLOW, theatre
from troupe.cli import main

YAML = ".troupe/actors/tester.yaml"
STEPS = 'actors.tester.options.script.steps=[{"exit": %d}]'


def cli(*argv: str) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(list(argv), stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


def ok(*argv: str) -> str:
    code, out, err = cli(*argv)
    assert code == 0, err
    return out


@pytest.fixture(name="repo")
def repo_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Repo:
    made = theatre(tmp_path)
    for name, value in {**made.env, **ADA, **ALLOW}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.chdir(made.path)
    return made


def _merge(repo: Repo) -> int:
    """``git merge feature`` into main, which may stop on a conflict."""
    return subprocess.run(
        ["git", "merge", "-q", "--no-edit", "feature"],  # noqa: S607 - git from the test's PATH
        cwd=repo.path,
        env={**repo.env, **AUTHOR},
        capture_output=True,
        check=False,
    ).returncode


BASE = [
    "actors.tester.runner=scripted",
    "actors.tester.expect=[]",
    'actors.tester.effects.write=["out/**"]',
    STEPS % 0,
]
"""A tester whose YAML ends in its options' last line followed by ``expect: []``: one branch
changing each puts the changes on adjacent lines, which git can't merge, while config can."""
