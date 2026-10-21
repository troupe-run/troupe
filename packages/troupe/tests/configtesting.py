"""Config's test helpers: an actor, changes recorded on real git branches, and a second runner
with its own options schema (config-model design D3, D4)."""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from gitrepo import Repo
from runtesting import INIT, OK, script
from storetesting import git_service
from troupe.core import interim
from troupe.core.config.changes import change
from troupe.core.config.merge import Merged
from troupe.core.config.stream import read, record

TESTER: dict[str, Any] = {
    "runner": "scripted",
    "options": script(INIT, OK),
    "expect": ["out/hello.txt"],
    "character": "You are the tester.",
}

Operations = Sequence[tuple[Sequence[str], object]]


def config_of(repo: Repo) -> Merged:
    return read(git_service(repo))


def set_config(repo: Repo, operations: Operations, *, commit: str | None = None) -> None:
    """Record one command's change on the repository's current branch, and commit it."""
    service = git_service(repo)
    merged = read(service)
    entries = change(merged.config, operations)
    record(service.command(via="cli"), merged, entries, [])
    repo.commit_all(commit or f"config: {[list(path) for path, _ in operations]}")


def branched(repo: Repo, base: Operations) -> None:
    """Record ``base`` on main, then make a branch ``feature`` from it, staying on main."""
    set_config(repo, base, commit="base")
    repo.git("branch", "feature")


def on(repo: Repo, branch: str, operations: Operations) -> None:
    repo.git("switch", "-q", branch)
    set_config(repo, operations)


def merged_feature(repo: Repo) -> Merged:
    repo.git("switch", "-q", "main")
    repo.git("merge", "-q", "--no-edit", "feature")
    return config_of(repo)


@pytest.fixture
def other_runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """A second runner, ``modelled``, whose options are only ``{"model": <string>}``."""
    package = tmp_path / "runner_modelled_for_tests"
    (package / "schemas").mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    options = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://troupe.run/plugins/runner-modelled/options.schema.json",
        "title": "Modelled runner options",
        "description": "Only a model.",
        "type": "object",
        "additionalProperties": False,
        "properties": {"model": {"description": "The model.", "type": "string"}},
    }
    (package / "schemas" / "options.schema.json").write_text(json.dumps(options), "utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    runners = {
        **interim.RUNNERS,
        "modelled": interim.Runner(command=("false",), package="runner_modelled_for_tests"),
    }
    monkeypatch.setattr(interim, "RUNNERS", runners)
    return "modelled"
