"""troupe's own size limits leave out the changelogs release-please writes, and still measure other
Markdown (spec: quality-check, "The size gate doesn't measure generated changelogs";
changelog-size-and-waiting-exit design D1)."""

import dataclasses
from collections.abc import Callable

from conftest import REPO, Repo, git

import quality_gates

BEFORE, AFTER = 48_910, 49_990
"""packages/troupe/CHANGELOG.md's size before and after the 0.4.0 release pull request (#533)."""


def troupe_size_limits() -> quality_gates.SizeConfig:
    """troupe's [size] as quality-gates.toml declares it, without [size.allow], whose files the
    throwaway repository doesn't have."""
    size = quality_gates.read_config(REPO).size
    assert size is not None
    return dataclasses.replace(size, allow={})


def grown(repo: Repo, path: str) -> None:
    """Commit path at BEFORE bytes, then grow it to AFTER in the working tree."""
    repo.write(path, "x" * (BEFORE - 1) + "\n")
    git(repo.path, "add", "-A")
    git(repo.path, "commit", "-q", "-m", "chore: base")
    repo.write(path, "x" * (AFTER - 1) + "\n")


def test_a_release_growing_core_s_changelog_past_the_limit_passes_the_size_gate(
    make_repo: Callable[[], Repo],
) -> None:
    repo = make_repo()
    grown(repo, "packages/troupe/CHANGELOG.md")
    result = quality_gates.size_result(repo.path, "HEAD", troupe_size_limits())
    assert result.problems == []
    assert not any("CHANGELOG.md" in note for note in result.notes)


def test_other_markdown_grown_past_the_limit_still_fails_the_size_gate(
    make_repo: Callable[[], Repo],
) -> None:
    repo = make_repo()
    grown(repo, "contributing/releasing.md")
    result = quality_gates.size_result(repo.path, "HEAD", troupe_size_limits())
    assert result.problems == [
        f"contributing/releasing.md: grew from {BEFORE:,} to {AFTER:,} bytes, above the limit of "
        "49,152"
    ]
