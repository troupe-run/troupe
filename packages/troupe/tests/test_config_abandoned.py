"""Finding the round trip a sweep closes, whether it can be dropped, and the keep record (spec:
config-hand-edits; abandoned-edits design D1, D2, D3, D7). Streams are made by real commands in a
real git theatre."""

import asyncio
from pathlib import Path
from typing import Any

import pytest

from configtesting import TESTER
from gitrepo import Repo, make_repo
from runtesting import INIT, OK, Harness, request, script
from storetesting import ADA, git_service
from troupe.core.client import messages as m
from troupe.core.client.dispatch import call
from troupe.core.client.session import Session
from troupe.core.config import aggregate
from troupe.core.config.abandoned import (
    KEPT,
    RoundTrip,
    blocked,
    head_sweep,
    kept,
    round_trip,
    write_kept,
)
from troupe.core.runs.perform import perform

TESTER_YAML = ".troupe/actors/tester.yaml"
TESTER_MD = ".troupe/actors/tester.md"


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


def _sync(repo: Repo) -> str | None:
    """Run troupe sync; the change id its sweep recorded, if any."""
    edits = _call(repo, "sync", {})["edits"]
    return edits[0]["change"] if edits else None


def _replace(repo: Repo, relative: str, old: str, new: str) -> None:
    path = repo.path / relative
    text = path.read_text("utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


def _started(repo: Repo) -> None:
    """A theatre with the tester, committed."""
    _set(repo, ["actors", "tester"], TESTER)
    repo.commit_all("tester")


def _trip(repo: Repo, closing: str | None) -> RoundTrip | None:
    assert closing is not None
    return round_trip(git_service(repo).history(aggregate.STREAM), closing)


# round_trip (design D1, D2)


def test_an_edit_undone_with_git_restore_is_a_round_trip_of_the_edit_and_the_edit_back(
    repo: Repo,
) -> None:
    _started(repo)
    _replace(repo, TESTER_YAML, "out/hello.txt", "out/a.txt")
    first = _sync(repo)
    repo.git("restore", TESTER_YAML)
    closing = _sync(repo)

    trip = _trip(repo, closing)

    assert trip is not None
    assert trip.changes == (first, closing)
    assert trip.files == ("actors/tester.yaml",)
    assert trip.outside is None


def test_values_back_with_a_new_comment_still_close_a_round_trip(repo: Repo) -> None:
    _started(repo)
    _replace(repo, TESTER_YAML, "out/hello.txt", "out/a.txt")
    _sync(repo)
    _replace(repo, TESTER_YAML, "out/a.txt", "out/hello.txt  # back again")
    assert _trip(repo, _sync(repo)) is not None


def test_several_steps_undone_are_one_round_trip(repo: Repo) -> None:
    _started(repo)
    _replace(repo, TESTER_YAML, "out/hello.txt", "out/a.txt")
    one = _sync(repo)
    _replace(repo, TESTER_YAML, "out/a.txt", "out/b.txt")
    two = _sync(repo)
    repo.git("restore", TESTER_YAML)
    closing = _sync(repo)
    trip = _trip(repo, closing)
    assert trip is not None
    assert trip.changes == (one, two, closing)


def test_a_partial_undo_closes_no_round_trip(repo: Repo) -> None:
    _started(repo)
    _replace(repo, TESTER_YAML, "out/hello.txt", "out/a.txt\nworkspace: theatre")
    _sync(repo)
    _replace(repo, TESTER_YAML, "out/a.txt", "out/hello.txt")
    assert _trip(repo, _sync(repo)) is None


def test_a_config_set_undone_by_git_restore_is_a_round_trip(repo: Repo) -> None:
    _started(repo)
    set_change = _set(repo, ["actors", "tester", "workspace"], "theatre")["change"]
    repo.git("restore", TESTER_YAML)
    closing = _sync(repo)
    trip = _trip(repo, closing)
    assert trip is not None
    assert trip.changes == (set_change, closing)


def test_of_two_round_trips_only_the_latest_is_closed(repo: Repo) -> None:
    _started(repo)
    _replace(repo, TESTER_YAML, "out/hello.txt", "out/a.txt")
    _sync(repo)
    _replace(repo, TESTER_YAML, "out/a.txt", "out/hello.txt")
    _sync(repo)
    _replace(repo, TESTER_YAML, "out/hello.txt", "out/a.txt")
    third = _sync(repo)
    repo.git("restore", TESTER_YAML)
    closing = _sync(repo)
    trip = _trip(repo, closing)
    assert trip is not None
    assert trip.changes == (third, closing)


def test_an_actor_deleted_and_restored_is_one_round_trip_with_both_files(repo: Repo) -> None:
    _started(repo)
    (repo.path / TESTER_YAML).unlink()
    (repo.path / TESTER_MD).unlink()
    removal = _sync(repo)
    repo.git("restore", TESTER_YAML, TESTER_MD)
    closing = _sync(repo)
    trip = _trip(repo, closing)
    assert trip is not None
    assert trip.changes == (removal, closing)
    assert sorted(trip.files) == ["actors/tester.md", "actors/tester.yaml"]
    assert trip.outside is None


def test_a_change_that_is_no_sweep_closes_nothing(repo: Repo) -> None:
    _started(repo)
    change = _set(repo, ["actors", "tester", "workspace"], "theatre")["change"]
    assert _trip(repo, change) is None


def test_a_round_trip_reaching_back_past_a_settle_is_not_looked_for(repo: Repo) -> None:
    _started(repo)
    repo.git("branch", "feature")
    _set(repo, ["actors", "tester", "workspace"], "theatre")
    repo.commit_all("main's change")
    repo.git("switch", "-q", "feature")
    _set(repo, ["actors", "tester", "expect"], ["out/other.txt"])
    repo.commit_all("feature's change")
    repo.git("switch", "-q", "main")
    repo.git("merge", "-q", "--no-edit", "feature")
    # The merge brings expect: [out/other.txt]; putting the file's expect back to main's before
    # the merge would reach back past the settle the next record makes.
    _replace(repo, TESTER_YAML, "out/other.txt", "out/hello.txt")
    assert _trip(repo, _sync(repo)) is None


# blocked (design D3)


def _abandoned(repo: Repo, old: str = "out/hello.txt", new: str = "out/a.txt") -> RoundTrip:
    _replace(repo, TESTER_YAML, old, new)
    _sync(repo)
    repo.git("restore", TESTER_YAML)
    trip = _trip(repo, _sync(repo))
    assert trip is not None
    return trip


def test_a_round_trip_alone_at_the_head_can_be_dropped(repo: Repo) -> None:
    _started(repo)
    assert blocked(git_service(repo), _abandoned(repo)) is None


def test_another_file_edited_in_between_changes_more(repo: Repo) -> None:
    _started(repo)
    _set(repo, ["actors", "reviewer"], TESTER)
    repo.commit_all("reviewer")
    _replace(repo, TESTER_YAML, "out/hello.txt", "out/a.txt")
    _sync(repo)
    _replace(repo, ".troupe/actors/reviewer.yaml", "out/hello.txt", "out/a.txt")
    reviewer = _sync(repo)
    repo.git("restore", TESTER_YAML)
    trip = _trip(repo, _sync(repo))
    assert trip is not None
    found = blocked(git_service(repo), trip)
    assert found is not None
    assert (found.reason, found.blocker) == ("changes-more", reviewer)


def test_a_config_set_after_it_builds_on_it(repo: Repo) -> None:
    _started(repo)
    trip = _abandoned(repo)
    later = _set(repo, ["actors", "tester", "workspace"], "theatre")["change"]
    found = blocked(git_service(repo), trip)
    assert found is not None
    assert (found.reason, found.blocker) == ("built-on", later)


def test_a_run_under_it_blocks_it_naming_the_run(tmp_path: Path) -> None:
    harness = Harness(make_repo(tmp_path, "theatre"))
    (harness.repo.path / ".troupe").mkdir()
    harness.configure(request(script(INIT, OK)))
    harness.repo.commit_all("tester")
    trip = _abandoned(harness.repo, "workspace: theatre", "workspace: worktree")
    parsed = m.PerformRequest.from_data({"actor": "tester", "direction": "go"})
    result = asyncio.run(
        perform(parsed, harness.session(), harness.send, backends=harness.backends())
    )
    assert result.run is not None
    found = blocked(git_service(harness.repo), trip)
    assert found is not None
    assert (found.reason, found.blocker) == ("run", result.run.run_id)


def test_a_run_about_to_start_blocks_it(repo: Repo) -> None:
    _started(repo)
    found = blocked(git_service(repo), _abandoned(repo), runs_now=True)
    assert found is not None
    assert (found.reason, found.blocker) == ("run", None)


def test_committed_events_block_it(repo: Repo) -> None:
    _started(repo)
    trip = _abandoned(repo)
    repo.commit_all("events")
    found = blocked(git_service(repo), trip)
    assert found is not None
    assert found.reason == "committed"


def test_a_round_trip_sharing_a_segment_is_blocked(repo: Repo) -> None:
    _started(repo)
    _set(repo, ["actors", "reviewer"], TESTER)
    repo.commit_all("reviewer")
    # One sync records both files' edits in one segment; restoring only one leaves the other's
    # event beside the round trip's first event.
    _replace(repo, ".troupe/actors/reviewer.yaml", "out/hello.txt", "out/a.txt")
    _replace(repo, TESTER_YAML, "out/hello.txt", "out/a.txt")
    _sync(repo)
    repo.git("restore", TESTER_YAML)
    trip = _trip(repo, _sync(repo))
    assert trip is not None
    assert trip.outside is None  # reviewer's edit comes before tester's, outside the trip
    found = blocked(git_service(repo), trip)
    assert found is not None
    assert found.reason == "shares-segment"


def test_head_sweep_names_the_sweep_at_the_head_only(repo: Repo) -> None:
    _started(repo)
    _replace(repo, TESTER_YAML, "out/hello.txt", "out/a.txt")
    closing = _sync(repo)
    history = git_service(repo).history(aggregate.STREAM)
    assert head_sweep(history) == closing
    _set(repo, ["actors", "tester", "workspace"], "theatre")
    assert head_sweep(git_service(repo).history(aggregate.STREAM)) is None


# The keep record (design D7)


def test_no_record_means_none_kept(tmp_path: Path) -> None:
    assert kept(tmp_path) == (frozenset(), [])


def test_an_unreadable_record_counts_as_none_and_is_named(tmp_path: Path) -> None:
    (tmp_path / KEPT).parent.mkdir(parents=True)
    (tmp_path / KEPT).write_bytes(b"{not json")
    found, notices = kept(tmp_path)
    assert found == frozenset()
    assert [(n.code, n.path) for n in notices] == [("config.kept-unreadable", str(tmp_path / KEPT))]


def test_keeping_twice_records_one_entry_and_prunes_gone_changes(tmp_path: Path) -> None:
    write_kept(tmp_path, frozenset({"a", "gone"}), frozenset({"a", "b"}))
    write_kept(tmp_path, kept(tmp_path)[0] | {"a"}, frozenset({"a", "b"}))
    assert kept(tmp_path) == (frozenset({"a"}), [])
    assert (tmp_path / KEPT).read_bytes() == b'["a"]\n'


def test_a_file_back_only_to_a_later_point_is_not_dropped_with_the_others(repo: Repo) -> None:
    # The yaml goes back to before change 1; the .md only to before change 3, so change 2 (the
    # character it still holds) is outside the files that went back: dropping would lose it.
    _started(repo)
    _set(repo, ["actors", "tester", "expect"], ["out/a.txt"])
    second = _set(repo, ["actors", "tester", "character"], "C1")["change"]
    _set(repo, ["actors", "tester", "character"], "C2")
    _replace(repo, TESTER_YAML, "out/a.txt", "out/hello.txt")
    (repo.path / TESTER_MD).write_text("C1", encoding="utf-8")
    trip = _trip(repo, _sync(repo))
    assert trip is not None
    assert trip.files == ("actors/tester.yaml",)
    assert trip.outside == second
    found = blocked(git_service(repo), trip)
    assert found is not None
    assert (found.reason, found.blocker) == ("changes-more", second)
