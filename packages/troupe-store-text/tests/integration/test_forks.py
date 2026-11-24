"""Forks and settling (spec: event-store, "A forked stream is detected" and "A settling event ends a
fork"; design D6; config-model design D5)."""

from pathlib import Path
from uuid import UUID

import pytest
from eventsourcing.domain import DomainEventProtocol
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
    assert caught.value.details["leftOut"] == [heads[1].id]


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


# An aggregate that merges its own forks reads its stream's history, and settles with its next
# change in one batch (config-model design D5).


def _set(stream: UUID, version: int, value: int) -> list[DomainEventProtocol[UUID]]:
    """A Counter's set event at ``version``, built without loading the stream."""
    loose = Counter(value=0)
    loose._id = stream
    loose._version = version - 1
    loose.set(value)
    return [e for e in loose.collect_events() if e.originator_version == version]


def test_a_forked_streams_history_is_read_whole_and_reading_it_records_nothing(
    tmp_path: Path,
) -> None:
    repo, stream = forked(tmp_path)
    before = sorted((repo.path / ".troupe" / "events").iterdir())
    history = git_service(repo).history(stream)
    assert [record.version for record in history] == [1, 2, 2]
    assert sorted((repo.path / ".troupe" / "events").iterdir()) == before


def test_one_batch_settles_a_fork_and_records_a_change_after_it(tmp_path: Path) -> None:
    repo, stream = forked(tmp_path)
    service = git_service(repo)
    heads = [head.id for head in service.recorder.heads(stream)]
    settled = Counter(value=12)
    settled._id = stream
    recorded = service.command(via="cli").record(
        [_settled(settled, 3), *_set(stream, 4, 13)], settles=heads
    )
    assert len(recorded) == 2
    assert service.forks() == []
    loaded = git_service(repo).load(stream)
    assert isinstance(loaded, Counter)
    assert (loaded.value, loaded.version) == (13, 4)
    *_, settling, change = git_service(repo).history(stream)
    assert sorted(settling.parents) == sorted(heads)
    assert change.parents == (settling.id,)


def test_a_batch_that_settles_and_changes_is_all_or_nothing(tmp_path: Path) -> None:
    repo, stream = forked(tmp_path)
    service = git_service(repo)
    heads = [head.id for head in service.recorder.heads(stream)]
    settled = Counter(value=12)
    settled._id = stream
    with pytest.raises(TroupeError) as caught:
        service.command(via="cli").record(
            [_settled(settled, 3), *_set(stream, 2, 13)],
            settles=heads,  # version 2 is taken
        )
    assert caught.value.code == "events.version-conflict"
    assert service.forks() == [stream]
    assert [record.version for record in git_service(repo).history(stream)] == [1, 2, 2]


def test_two_clones_that_settle_a_fork_the_same_way_record_one_settling_event(
    tmp_path: Path,
) -> None:
    repo, stream = forked(tmp_path)
    repo.commit_all("merged")
    repo.git("branch", "elsewhere")
    settled = Counter(value=12)
    settled._id = stream
    for branch in ("main", "elsewhere"):
        repo.git("switch", "-q", branch)
        service = git_service(repo)
        heads = [head.id for head in service.recorder.heads(stream)]
        service.command(via="cli").record([_settled(settled, 3)], settles=heads)
        repo.commit_all(f"settled on {branch}")
    repo.git("switch", "-q", "main")
    repo.git("merge", "-q", "--no-edit", "elsewhere")
    service = git_service(repo)
    assert service.forks() == []
    history = service.history(stream)
    assert [record.version for record in history] == [1, 2, 2, 3]
    assert len(service.recordings(history[-1].id)) == 2
