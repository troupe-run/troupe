"""Lineage types agree with protocol/schemas/lineage.schema.json (spec: lineage, "Lineage is defined
once, language-neutrally"; design D8)."""

import copy
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from event_schemas import LINEAGE, is_valid, lineage, without
from troupe.core.events.lineage import (
    VIA,
    Actor,
    Approval,
    Cause,
    CommandCause,
    EventCause,
    Lineage,
    Source,
    Unknown,
    VcsState,
    lineage_problem,
    timestamp,
)
from troupe.core.identity import Identity
from troupe.core.ulid import new_ulid

HASH = "sha256:" + "ab" * 32
ACTORS: list[Actor] = [
    Identity(kind="human", id="ada@example.com", source="vcs"),
    Identity(kind="agent", id="tester", source="troupe"),
    Unknown(),
]
SOURCES = [
    None,
    Source(path="actors/tester.yaml", before=HASH, after=HASH),
    Source(path="new.yaml", before=None, after=HASH),
    Source(path="gone.yaml", before=HASH, after=None),
]


def build(actor: Actor, via: str, cause: Cause, source: Source | None, change: str) -> Lineage:
    return Lineage(
        actor=actor,
        via=via,  # type: ignore[arg-type]
        at=timestamp(datetime(2026, 10, 12, 3, 4, 5, 678901, tzinfo=UTC)),
        reason=None,
        change=change,
        cause=cause,
        vcs=VcsState(adapter="git", branch="main", head="a" * 40, source=source),
    )


@pytest.mark.parametrize("actor", ACTORS, ids=["human", "agent", "unknown"])
@pytest.mark.parametrize("via", VIA)
@pytest.mark.parametrize("cause_kind", ["command", "event"])
@pytest.mark.parametrize("source", SOURCES, ids=["no file", "edited", "created", "deleted"])
def test_every_lineage_troupe_builds_validates_against_the_schema(
    actor: Actor, via: str, cause_kind: str, source: Source | None
) -> None:
    change = new_ulid()
    cause: Cause = CommandCause(change) if cause_kind == "command" else EventCause(HASH)
    data = build(actor, via, cause, source, change).to_data()
    assert is_valid(data, "lineage.schema.json")
    assert lineage_problem(data) is None


def test_lineage_with_an_approval_and_a_reason_validates() -> None:
    change = new_ulid()
    built = build(ACTORS[0], "cli", CommandCause(change), None, change)
    data = Lineage(
        actor=built.actor,
        via=built.via,
        at=built.at,
        reason="tidy up",
        change=change,
        cause=built.cause,
        vcs=built.vcs,
        approvals=(Approval(actor=ACTORS[0], role="owner", at=built.at),),
    ).to_data()
    assert is_valid(data, "lineage.schema.json")
    assert lineage_problem(data) is None


INVALID: list[dict[str, Any]] = [
    lineage(actor=None),
    without(LINEAGE, "actor"),
    lineage(actor={"kind": "unknown", "id": "ada"}),
    lineage(actor={"kind": "human", "id": "", "source": "env"}),
    lineage(actor={"kind": "human", "id": "ada"}),
    lineage(colour="blue"),
    lineage(via="email"),
    lineage(at="2026-10-12T03:04:05+10:00"),
    lineage(at=float("nan")),
    without(LINEAGE, "reason"),
    lineage(reason=""),
    lineage(cause=None),
    without(LINEAGE, "cause"),
    lineage(cause={"kind": "timer", "id": new_ulid()}),
    lineage(cause={"kind": "event", "id": new_ulid()}),
    lineage(cause={"kind": "command", "id": HASH}),
    lineage(change="not-a-ulid"),
    lineage(approvals=[{"actor": {"kind": "unknown"}, "role": "", "at": LINEAGE["at"]}]),
    lineage(vcs={"adapter": "git", "branch": "", "head": None, "source": None}),
    lineage(
        vcs={
            "adapter": "git",
            "branch": "main",
            "head": None,
            "source": {"path": "/abs/x.yaml", "before": None, "after": HASH},
        }
    ),
    lineage(
        vcs={
            "adapter": "git",
            "branch": "main",
            "head": None,
            "source": {"path": "a\\b.yaml", "before": None, "after": HASH},
        }
    ),
    lineage(
        vcs={
            "adapter": "git",
            "branch": "main",
            "head": None,
            "source": {"path": "../x.yaml", "before": None, "after": HASH},
        }
    ),
    lineage(
        vcs={
            "adapter": "git",
            "branch": "main",
            "head": None,
            "source": {"path": "C:x.yaml", "before": None, "after": HASH},
        }
    ),
    lineage(
        vcs={
            "adapter": "git",
            "branch": "main",
            "head": None,
            "source": {"path": "x.yaml", "before": "md5:abc", "after": HASH},
        }
    ),
]


@pytest.mark.parametrize("data", INVALID)
def test_the_hand_written_check_refuses_exactly_what_the_schema_refuses(
    data: dict[str, Any],
) -> None:
    assert not is_valid(data, "lineage.schema.json")
    assert lineage_problem(data) is not None


def test_the_hand_written_check_names_the_field_at_fault() -> None:
    assert "actor" in (lineage_problem(lineage(actor=None)) or "")
    assert "cause" in (lineage_problem(copy.deepcopy(lineage(cause=None))) or "")
    assert "via" in (lineage_problem(lineage(via="email")) or "")


@pytest.mark.parametrize(
    "moment",
    [
        datetime(2026, 10, 12, 13, 4, 5, 678901, tzinfo=timezone(timedelta(hours=10))),
        datetime(2026, 10, 12, 3, 4, 5, 678901, tzinfo=UTC),
    ],
)
def test_times_are_written_in_utc_with_milliseconds_and_z(moment: datetime) -> None:
    assert timestamp(moment) == "2026-10-12T03:04:05.678Z"
