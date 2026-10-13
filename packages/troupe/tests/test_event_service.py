"""The event-store service (spec: lineage, identity, event-store; design D8, D9; #1's rules on
abandoned edits)."""

import hashlib
import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from event_schemas import is_valid
from gitrepo import make_repo
from storetesting import ADA, Counter, files_service, git_service, segments, snapshot
from troupe.core import strict_json
from troupe.core.errors import TroupeError
from troupe.core.events import (
    Allowance,
    CommandCause,
    EventStore,
    Lineage,
    Source,
    StageLineage,
    Unknown,
    VcsState,
    load_store,
)
from troupe.core.events.lineage import timestamp
from troupe.core.identity import Identity
from troupe.core.vcs import load_vcs
from troupe_identity_local import EnvSource, OsLoginSource, VcsSource


def recorded_lines(theatre: Path) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    for path in segments(theatre):
        lines.extend(json.loads(raw) for raw in path.read_bytes().splitlines()[1:])
    return lines


def lineage_of(theatre: Path, event_id: str) -> dict[str, Any]:
    [line] = [line for line in recorded_lines(theatre) if line["id"] == event_id]
    lineage: dict[str, Any] = line["state"]["lineage"]
    return lineage


# Lineage on every recorded event.


def test_every_recorded_line_carries_lineage_that_the_schema_accepts(tmp_path: Path) -> None:
    service = files_service(tmp_path)
    service.command(via="cli").record(Counter(value=1).collect_events())
    [line] = recorded_lines(tmp_path)
    assert is_valid(line, "event-record.schema.json#/$defs/troupeEvent")


def test_an_invalid_lineage_names_the_field_and_writes_nothing(tmp_path: Path) -> None:
    service = files_service(tmp_path)
    command = service.command(via="cli")
    good = command.lineage()
    bad = Lineage(
        actor=good.actor,
        via="email",  # type: ignore[arg-type]
        at=good.at,
        reason=None,
        change=good.change,
        cause=good.cause,
        vcs=good.vcs,
    )
    with pytest.raises(TroupeError) as caught:
        service.record_with_lineage(Counter(value=1).collect_events(), bad)
    assert caught.value.code == "events.lineage-invalid"
    assert "via" in caught.value.problem
    assert snapshot(tmp_path) == {}


def test_a_command_run_by_a_person_records_a_human_actor_with_its_source(
    tmp_path: Path,
) -> None:
    service = files_service(tmp_path)
    [recorded] = service.command(via="cli").record(Counter(value=1).collect_events())
    actor = lineage_of(tmp_path, recorded.event_id)["actor"]
    assert actor == {"kind": "human", "id": "ada@example.com", "source": "env"}


def test_a_hand_edit_records_an_explicit_unknown_actor_with_the_files_hashes(
    tmp_path: Path,
) -> None:
    service = files_service(tmp_path)
    before = "sha256:" + hashlib.sha256(b"workers: 3\n").hexdigest()
    after = "sha256:" + hashlib.sha256(b"workers: 5\n").hexdigest()
    source = Source(path="actors/tester.yaml", before=before, after=after)
    [recorded] = service.command(via="file", actor=Unknown()).record(
        Counter(value=5).collect_events(), source=source
    )
    lineage = lineage_of(tmp_path, recorded.event_id)
    assert lineage["actor"] == {"kind": "unknown"}
    assert lineage["via"] == "file"
    assert lineage["vcs"]["source"] == {
        "path": "actors/tester.yaml",
        "before": before,
        "after": after,
    }
    assert is_valid(lineage, "lineage.schema.json")


def test_one_commands_events_share_its_change_id_and_another_commands_differ(
    tmp_path: Path,
) -> None:
    service = files_service(tmp_path)
    first = service.command(via="cli").record(
        [*Counter(value=1).collect_events(), *Counter(value=2).collect_events()]
    )
    [second] = service.command(via="cli").record(Counter(value=3).collect_events())
    changes = [lineage_of(tmp_path, r.event_id)["change"] for r in first]
    assert changes[0] == changes[1]
    assert lineage_of(tmp_path, second.event_id)["change"] != changes[0]


def test_lineage_time_is_utc_from_the_clock(tmp_path: Path) -> None:
    sydney = datetime(2026, 10, 12, 13, 4, 5, 678000, tzinfo=timezone(timedelta(hours=10)))
    service = files_service(tmp_path, clock=lambda: sydney)
    [recorded] = service.command(via="cli").record(Counter(value=1).collect_events())
    assert lineage_of(tmp_path, recorded.event_id)["at"] == "2026-10-12T03:04:05.678Z"


def test_an_event_recorded_on_a_git_branch_names_the_adapter_branch_and_head(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    head = repo.commit_all()
    [recorded] = git_service(repo).command(via="cli").record(Counter(value=1).collect_events())
    vcs = lineage_of(repo.path, recorded.event_id)["vcs"]
    assert vcs == {"adapter": "git", "branch": "main", "head": head, "source": None}


def test_a_theatre_without_version_control_records_null_branch_and_head(
    tmp_path: Path,
) -> None:
    [recorded] = files_service(tmp_path).command(via="cli").record(Counter().collect_events())
    vcs = lineage_of(tmp_path, recorded.event_id)["vcs"]
    assert vcs == {"adapter": "files", "branch": None, "head": None, "source": None}


def test_with_no_identity_a_command_fails_before_anything_is_written(tmp_path: Path) -> None:
    def no_login() -> str:
        raise OSError("no login")

    vcs = files_service(tmp_path).vcs
    service = EventStore(
        tmp_path,
        vcs=vcs,
        recorder=files_service(tmp_path).recorder,
        env={},
        identity_sources=[
            ("env", EnvSource()),
            ("vcs", VcsSource()),
            ("os-login", OsLoginSource(lookup=no_login)),
        ],
    )
    with pytest.raises(TroupeError) as caught:
        service.command(via="cli")
    assert caught.value.code == "identity.unresolved"
    assert snapshot(tmp_path) == {}


def test_two_commands_changing_the_same_state_conflict_on_the_second(tmp_path: Path) -> None:
    service = files_service(tmp_path)
    counter = Counter(value=1)
    service.command(via="cli").record(counter.collect_events())
    first, second = service.load(counter.id), service.load(counter.id)
    assert isinstance(first, Counter)
    assert isinstance(second, Counter)
    first.set(2)
    second.set(3)
    service.command(via="cli").record(first.collect_events())
    with pytest.raises(TroupeError) as caught:
        service.command(via="cli").record(second.collect_events())
    assert caught.value.code == "events.version-conflict"


def test_an_agent_troupe_assigns_is_recorded_as_the_actor(tmp_path: Path) -> None:
    agent = Identity(kind="agent", id="tester", source="troupe")
    [recorded] = (
        files_service(tmp_path)
        .command(via="runner", actor=agent)
        .record(Counter().collect_events())
    )
    actor = lineage_of(tmp_path, recorded.event_id)["actor"]
    assert actor == {"kind": "agent", "id": "tester", "source": "troupe"}


def test_reads_return_the_stores_notices(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.commit_all()
    git_service(repo).command(via="cli").record(Counter().collect_events())
    repo.git("switch", "-q", "-c", "other")
    assert [n.code for n in git_service(repo).notices()] == ["events.other-branch"]


# Abandoned edits (#1, 2026-10-12): recorded as a change and a change back; nothing classified.


def test_an_edit_and_its_revert_both_stay_recorded(tmp_path: Path) -> None:
    service = files_service(tmp_path)
    counter = Counter(value=3)
    service.command(via="cli").record(counter.collect_events())
    for value in (5, 3):
        loaded = service.load(counter.id)
        assert isinstance(loaded, Counter)
        loaded.set(value)
        service.command(via="file", actor=Unknown()).record(loaded.collect_events())
    values = [strict_json.loads(r.state)["value"] for r in service.history(counter.id)]  # type: ignore[index]
    assert values == [3, 5, 3]


def test_events_recorded_around_a_stash_and_pop_are_all_present_in_order(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    repo.write("actors/tester.yaml", "workers: 3\n")
    repo.commit_all()
    counter = Counter(value=3)
    git_service(repo).command(via="cli").record(counter.collect_events())
    for value, git in ((5, ("stash",)), (3, ("stash", "pop")), (5, ())):
        repo.write("actors/tester.yaml", f"workers: {value}\n")
        service = git_service(repo)
        loaded = service.load(counter.id)
        assert isinstance(loaded, Counter)
        loaded.set(value)
        service.command(via="file", actor=Unknown()).record(loaded.collect_events())
        if git:
            repo.git(*git)
    history = git_service(repo).history(counter.id)
    assert [strict_json.loads(r.state)["value"] for r in history] == [3, 5, 3, 5]  # type: ignore[index]


# Correlation and cause (design D8).


def test_a_commands_own_events_name_the_command_as_their_cause(tmp_path: Path) -> None:
    service = files_service(tmp_path)
    [recorded] = service.command(via="cli").record(Counter().collect_events())
    lineage = lineage_of(tmp_path, recorded.event_id)
    assert lineage["cause"] == {"kind": "command", "id": lineage["change"]}


def test_reactions_to_an_event_carry_its_change_and_name_it_as_their_cause(
    tmp_path: Path,
) -> None:
    service = files_service(tmp_path)
    [e1] = service.command(via="cli").record(Counter(value=1).collect_events())
    reactions = [
        service.record_reaction(e1.event_id, Counter(value=n).collect_events(), via="cli")[0]
        for n in (2, 3, 4)
    ]
    change = lineage_of(tmp_path, e1.event_id)["change"]
    for reaction in reactions:
        lineage = lineage_of(tmp_path, reaction.event_id)
        assert lineage["change"] == change
        assert lineage["cause"] == {"kind": "event", "id": e1.event_id}


def test_a_reaction_to_a_reaction_keeps_the_original_change(tmp_path: Path) -> None:
    service = files_service(tmp_path)
    [e1] = service.command(via="cli").record(Counter(value=1).collect_events())
    [e2] = service.record_reaction(e1.event_id, Counter(value=2).collect_events(), via="cli")
    [e5] = service.record_reaction(e2.event_id, Counter(value=5).collect_events(), via="cli")
    lineage = lineage_of(tmp_path, e5.event_id)
    assert lineage["change"] == lineage_of(tmp_path, e1.event_id)["change"]
    assert lineage["cause"] == {"kind": "event", "id": e2.event_id}


def test_a_cause_that_names_no_event_is_refused_and_nothing_is_written(tmp_path: Path) -> None:
    service = files_service(tmp_path)
    missing = "sha256:" + "00" * 32
    with pytest.raises(TroupeError) as caught:
        service.record_reaction(missing, Counter().collect_events(), via="cli")
    assert caught.value.code == "events.cause-unknown"
    assert missing in caught.value.problem
    assert snapshot(tmp_path) == {}


def test_a_command_cause_that_disagrees_with_the_change_id_is_refused(tmp_path: Path) -> None:
    service = files_service(tmp_path)
    command = service.command(via="cli")
    other = service.command(via="cli")
    mismatched = Lineage(
        actor=command.actor,
        via="cli",
        at=timestamp(datetime.now(tz=UTC)),
        reason=None,
        change=command.change,
        cause=CommandCause(other.change),
        vcs=VcsState(adapter="files", branch=None, head=None),
    )
    with pytest.raises(TroupeError) as caught:
        service.record_with_lineage(Counter().collect_events(), mismatched)
    assert caught.value.code == "events.lineage-invalid"
    assert snapshot(tmp_path) == {}


def test_the_default_actor_comes_from_the_identity_chain(tmp_path: Path) -> None:
    service = files_service(tmp_path, env=ADA)
    assert service.command(via="cli").actor == Identity(
        kind="human", id="ada@example.com", source="env"
    )


# The stage a run ran on, and one command recording as several actors (perform-status-logs D7, D8).

LOCAL = StageLineage(
    name="local",
    effects="unenforced",
    allowed_by=Allowance(setting="allow_unenforced_local_stage", source="env"),
)
TESTER = Identity(kind="agent", id="tester", source="troupe")


def test_an_event_recorded_outside_a_stage_has_a_null_stage(tmp_path: Path) -> None:
    service = files_service(tmp_path)
    [recorded] = service.command(via="cli").record(Counter(value=1).collect_events())
    assert lineage_of(tmp_path, recorded.event_id)["stage"] is None


def test_a_commands_stage_is_recorded_in_the_lineage_of_every_event_it_records(
    tmp_path: Path,
) -> None:
    service = files_service(tmp_path)
    recorded = service.command(via="cli", stage=LOCAL).record(Counter(value=1).collect_events())
    assert recorded
    for each in recorded:
        assert lineage_of(tmp_path, each.event_id)["stage"] == {
            "name": "local",
            "effects": "unenforced",
            "allowedBy": {"setting": "allow_unenforced_local_stage", "source": "env"},
        }


def test_an_unenforced_stage_naming_no_allowance_is_refused_and_writes_nothing(
    tmp_path: Path,
) -> None:
    service = files_service(tmp_path)
    # StageLineage refuses to be built this way, so go around it: the service is the second check.
    unallowed = object.__new__(StageLineage)
    object.__setattr__(unallowed, "name", "local")
    object.__setattr__(unallowed, "effects", "unenforced")
    object.__setattr__(unallowed, "allowed_by", None)
    good = service.command(via="cli").lineage()
    bad = Lineage(
        actor=good.actor,
        via=good.via,
        at=good.at,
        reason=None,
        change=good.change,
        cause=good.cause,
        vcs=good.vcs,
        stage=unallowed,
    )
    with pytest.raises(TroupeError) as caught:
        service.record_with_lineage(Counter(value=1).collect_events(), bad)
    assert caught.value.code == "events.lineage-invalid"
    assert "stage" in caught.value.problem
    assert snapshot(tmp_path) == {}


def test_a_command_acting_as_another_actor_shares_its_change_id_cause_and_stage(
    tmp_path: Path,
) -> None:
    service = files_service(tmp_path)
    person = service.command(via="cli", stage=LOCAL)
    agent = person.acting_as(TESTER, via="runner")
    [first] = person.record(Counter(value=1).collect_events())
    [second] = agent.record(Counter(value=2).collect_events())
    by_person = lineage_of(tmp_path, first.event_id)
    by_agent = lineage_of(tmp_path, second.event_id)
    assert by_person["change"] == by_agent["change"] == person.change
    assert by_person["cause"] == by_agent["cause"] == {"kind": "command", "id": person.change}
    assert by_agent["stage"] == by_person["stage"] == LOCAL.to_data()
    assert by_person["actor"] == {"kind": "human", "id": "ada@example.com", "source": "env"}
    assert by_person["via"] == "cli"
    assert by_agent["actor"] == {"kind": "agent", "id": "tester", "source": "troupe"}
    assert by_agent["via"] == "runner"


def test_each_recorded_event_carries_the_time_its_lineage_records(tmp_path: Path) -> None:
    service = files_service(tmp_path)
    recorded = service.command(via="cli").record(Counter(value=1).collect_events())
    assert recorded
    for each in recorded:
        assert each.at == lineage_of(tmp_path, each.event_id)["at"]


def test_an_event_store_that_is_not_installed_is_refused_naming_the_installed_ones(
    tmp_path: Path,
) -> None:
    with pytest.raises(TroupeError) as caught:
        load_store("nope", tmp_path, load_vcs("files", tmp_path))
    assert caught.value.code == "events.unknown-store"
    assert caught.value.details["store"] == "nope"
    assert "text" in caught.value.details["installed"]
