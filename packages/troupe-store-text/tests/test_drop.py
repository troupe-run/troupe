"""A person's drop of whole uncommitted segments (spec: event-store, "A drop removes only whole
uncommitted segments of this branch"; abandoned-edits design D4)."""

import time
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from gitrepo import Repo, make_repo
from storetesting import event, segments
from troupe.core.errors import TroupeError
from troupe_store_text.store import TextStore
from troupe_vcs_git import GitAdapter


def _session(repo: Repo) -> TextStore:
    """A new session's store: its first record starts its own segment."""
    return TextStore(repo.path, GitAdapter(repo.path, source=repo.env))


def _record(repo: Repo, stream: UUID, version: int, count: int = 1) -> list[str]:
    """Record ``count`` events of ``stream`` from ``version``, in one new session's segment, and
    return their ids."""
    store = _session(repo)
    store.insert([event(stream, version + n, n=version + n) for n in range(count)])
    return [r.id for r in store.history(stream)][version - 1 :]


def _no_check() -> None:
    return None


def _refusal(store: TextStore, events: list[str]) -> TroupeError:
    with pytest.raises(TroupeError) as raised:
        store.drop(events, _no_check)
    assert raised.value.code == "events.not-droppable"
    return raised.value


def test_events_alone_in_their_uncommitted_segments_are_dropped_and_the_order_rebuilt(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    repo.commit_all()
    stream = uuid4()
    first = _record(repo, stream, 1)
    time.sleep(0.01)
    second = _record(repo, stream, 2)
    store = _session(repo)
    store.notifications(1, 10, None, [])  # number them, so the drop has an order to rebuild
    assert store.droppable([*first, *second]) is None
    before = segments(repo.path)

    removed = store.drop([*first, *second], _no_check)

    assert sorted(removed) == before
    assert segments(repo.path) == []
    reader = _session(repo)
    assert reader.history(stream) == []
    assert [n.code for n in store.notices()] == ["events.order-rebuilt"]


def test_one_of_two_events_in_a_segment_is_refused_naming_the_segment(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.commit_all()
    stream = uuid4()
    both = _record(repo, stream, 1, count=2)
    store = _session(repo)
    assert store.droppable(both[1:]) == "shares-segment"

    error = _refusal(store, both[1:])

    assert error.details["reason"] == "shares-segment"
    assert error.details["segments"] == [str(p) for p in segments(repo.path)]
    assert len(segments(repo.path)) == 1


def test_a_committed_segment_is_refused_as_committed(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.commit_all()
    stream = uuid4()
    ids = _record(repo, stream, 1)
    repo.commit_all("events")
    store = _session(repo)

    error = _refusal(store, ids)

    assert error.details["reason"] == "committed"
    assert len(segments(repo.path)) == 1


def test_a_staged_segment_counts_as_committed(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.commit_all()
    ids = _record(repo, uuid4(), 1)
    repo.git("add", ".troupe/events")
    assert _session(repo).droppable(ids) == "committed"


def test_an_event_a_later_event_follows_is_refused_naming_the_later_event(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    repo.commit_all()
    stream = uuid4()
    first = _record(repo, stream, 1)
    time.sleep(0.01)
    later = _record(repo, stream, 2)
    store = _session(repo)

    error = _refusal(store, first)

    assert error.details["reason"] == "parent"
    assert error.details["event"] == later[0]
    assert len(segments(repo.path)) == 2


def test_a_refusing_check_run_under_the_lock_removes_nothing(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.commit_all()
    ids = _record(repo, uuid4(), 1)
    store = _session(repo)
    ran: list[bool] = []

    def check() -> None:
        ran.append(store._holding)  # the check runs holding the write lock
        raise TroupeError(
            "events.not-droppable",
            problem="p",
            fix="f",
            details={"reason": "parent", "segments": []},
        )

    with pytest.raises(TroupeError):
        store.drop(ids, check)
    assert ran == [True]
    assert len(segments(repo.path)) == 1


def test_a_session_that_dropped_its_own_segment_starts_a_new_one(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.commit_all()
    store = _session(repo)
    stream = uuid4()
    store.insert([event(stream, 1)])
    ids = [r.id for r in store.history(stream)]
    store.drop(ids, _no_check)
    other = uuid4()
    store.insert([event(other, 1)])
    assert len(segments(repo.path)) == 1
    assert [r.version for r in _session(repo).history(other)] == [1]


def test_an_unknown_event_is_refused(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.commit_all()
    _record(repo, uuid4(), 1)
    error = _refusal(_session(repo), ["sha256:" + "0" * 64])
    assert error.details["reason"] == "unknown-event"
