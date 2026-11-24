"""Helpers that test_perform.py shares with other test modules."""

from typing import Any

from runtesting import Harness
from storetesting import git_service, snapshot
from troupe.core.config import projection
from troupe.core.config.stream import read as read_config

# 7.5: refusals leave nothing behind.


def configured(harness: Harness, asked: dict[str, Any]) -> dict[str, str]:
    """Define the actor in config, then snapshot .troupe/: what perform must leave as it is."""
    harness.configure(asked)
    projection.flush(
        harness.repo.path, read_config(git_service(harness.repo)).config, {}
    )  # the files too, so a refused perform has nothing to flush either
    return snapshot(harness.repo.path / ".troupe")


def nothing_written(harness: Harness, before: dict[str, str]) -> bool:
    return snapshot(harness.repo.path / ".troupe") == before


FAKE_SECRET = "s3cret"  # noqa: S105 - a stand-in value, checked for where it never arrives
