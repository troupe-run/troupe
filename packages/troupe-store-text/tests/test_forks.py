"""Forks and settling (spec: event-store, "A forked stream is detected" and "A settling event ends a
fork"; design D6)."""

from pathlib import Path
from uuid import UUID

import pytest
from eventsourcing.utils import get_topic

from gitrepo import Repo, make_repo
from storetesting import Counter, git_service
from troupe.core.errors import TroupeError
from troupe.core.events import Settled


def forked(tmp_path: Path) -> tuple[Repo, UUID]:
    """A Counter set to 5 on one branch and 7 on another, then merged: two heads at version 2."""
    repo = make_repo(tmp_path)
    counter = Counter(value=1)
    git_service(repo).command(via="cli").record(counter.collect_events())
    repo.commit_all("created")
    repo.git("switch", "-q", "-c", "feature")
    for value, branch in ((5, "feature"), (7, "main")):
        repo.git("switch", "-q", branch)
        service = git_service(repo)
        loaded = service.load(counter.id)
        assert isinstance(loaded, Counter)
        loaded.set(value)
        service.command(via="cli").record(loaded.collect_events())
        repo.commit_all(f"set {value} on {branch}")
    repo.git("merge", "-q", "--no-edit", "feature")
    return repo, counter.id


def test_a_stream_appended_on_two_branches_is_refused_naming_both_heads_and_their_files(
    tmp_path: Path,
) -> None:
    repo, stream = forked(tmp_path)
    service = git_service(repo)
    with pytest.raises(TroupeError) as caught:
        service.load(stream)
    assert caught.value.code == "events.stream-forked"
    heads = caught.value.details["heads"]
    assert len(heads) == 2
    assert {head["version"] for head in heads} == {2}
    assert all(Path(head["file"]).exists() for head in heads)
    assert "Settle the fork" in caught.value.fix
    assert service.forks() == [stream]


def test_appending_to_a_forked_stream_is_refused_with_the_same_error(tmp_path: Path) -> None:
    repo, stream = forked(tmp_path)
    loose = Counter(value=0)
    loose._id = stream  # an aggregate built without loading: it can't know about the fork
    loose._version = 2
    loose.set(9)
    pending = [e for e in loose.collect_events() if e.originator_version == 3]
    with pytest.raises(TroupeError) as caught:
        git_service(repo).command(via="cli").record(pending)
    assert caught.value.code == "events.stream-forked"


def test_settling_a_fork_leaves_one_head_and_loads_the_settled_state_plus_later_events(
    tmp_path: Path,
) -> None:
    repo, stream = forked(tmp_path)
    service = git_service(repo)
    settled = Counter(value=12)
    settled._id = stream
    recorded = service.command(via="cli", reason="5 and 7 settle at 12").settle(settled)
    assert service.forks() == []
    loaded = service.load(stream)
    assert isinstance(loaded, Counter)
    assert (loaded.value, loaded.version) == (12, 3)
    assert [e.id for e in [*git_service(repo).history(stream)][-1:]] == [recorded.event_id]

    loaded.set(13)
    service.command(via="cli").record(loaded.collect_events())
    again = git_service(repo).load(stream)
    assert isinstance(again, Counter)
    assert (again.value, again.version) == (13, 4)


def test_a_settling_event_must_name_every_head(tmp_path: Path) -> None:
    repo, stream = forked(tmp_path)
    service = git_service(repo)
    heads = service.recorder.heads(stream)
    one = Counter(value=12)
    one._id = stream
    command = service.command(via="cli")
    with pytest.raises(TroupeError) as caught:
        service.record_with_lineage(
            [_settled(one, 3)], command.lineage(), settling_parents=[heads[0].id]
        )
    assert caught.value.code == "events.settle-incomplete"
    assert caught.value.details["left_out"] == [heads[1].id]


def test_a_settled_streams_history_keeps_both_branches_and_the_settling_event(
    tmp_path: Path,
) -> None:
    repo, stream = forked(tmp_path)
    service = git_service(repo)
    settled = Counter(value=12)
    settled._id = stream
    service.command(via="cli").settle(settled)
    versions = [record.version for record in service.history(stream)]
    assert versions == [1, 2, 2, 3]
    assert len(service.history(stream)[-1].parents) == 2


def _settled(aggregate: Counter, version: int) -> Settled:
    return Settled(
        originator_id=aggregate.id,
        originator_version=version,
        timestamp=Settled.create_timestamp(),
        topic=get_topic(type(aggregate)),
        state={"value": aggregate.value},
    )
