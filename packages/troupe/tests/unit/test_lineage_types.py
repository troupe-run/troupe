"""Lineage types agree with protocol/schemas/lineage.schema.json (spec: lineage, "Lineage is defined
once, language-neutrally"; design D8)."""

import copy
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from event_schemas import ENFORCED, LINEAGE, UNENFORCED_LOCAL, is_valid, lineage, without
from troupe.core.events.lineage import (
    VIA,
    Actor,
    Allowance,
    Approval,
    Cause,
    CommandCause,
    EventCause,
    Lineage,
    Source,
    StageLineage,
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

STAGES = [
    None,
    StageLineage(
        name="local",
        effects="unenforced",
        allowed_by=Allowance(setting="allow_unenforced_local_stage", source="env"),
    ),
    StageLineage(name="docker", effects="enforced", allowed_by=None),
]


def build(
    actor: Actor,
    via: str,
    cause: Cause,
    source: Source | None,
    change: str,
    stage: StageLineage | None = None,
) -> Lineage:
    return Lineage(
        actor=actor,
        via=via,  # type: ignore[arg-type]
        at=timestamp(datetime(2026, 10, 12, 3, 4, 5, 678901, tzinfo=UTC)),
        reason=None,
        change=change,
        cause=cause,
        vcs=VcsState(adapter="git", branch="main", head="a" * 40, source=source),
        stage=stage,
    )


@pytest.mark.parametrize("actor", ACTORS, ids=["human", "agent", "unknown"])
@pytest.mark.parametrize("via", VIA)
@pytest.mark.parametrize("cause_kind", ["command", "event"])
@pytest.mark.parametrize("source", SOURCES, ids=["no file", "edited", "created", "deleted"])
@pytest.mark.parametrize("stage", STAGES, ids=["no stage", "unenforced", "enforced"])
def test_every_lineage_troupe_builds_validates_against_the_schema(
    actor: Actor, via: str, cause_kind: str, source: Source | None, stage: StageLineage | None
) -> None:
    change = new_ulid()
    cause: Cause = CommandCause(change) if cause_kind == "command" else EventCause(HASH)
    data = build(actor, via, cause, source, change, stage).to_data()
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
    lineage(reason=None),
    lineage(reason=""),
    lineage(cause=None),
    without(LINEAGE, "cause"),
    lineage(cause={"kind": "timer", "id": new_ulid()}),
    lineage(cause={"kind": "event", "id": new_ulid()}),
    lineage(cause={"kind": "command", "id": HASH}),
    lineage(change="not-a-ulid"),
    lineage(approvals=[{"actor": {"kind": "unknown"}, "role": "", "at": LINEAGE["at"]}]),
    lineage(vcs={"adapter": "git", "branch": ""}),
    lineage(vcs={"adapter": "git", "branch": None}),
    lineage(vcs={"adapter": "git", "head": None}),
    lineage(vcs={"adapter": "git", "source": None}),
    lineage(vcs={"branch": "main"}),
    lineage(vcs={"adapter": "git", "source": {"path": "x.yaml", "before": None, "after": HASH}}),
    lineage(vcs={"adapter": "git", "source": {"path": "x.yaml", "before": HASH, "after": None}}),
    lineage(vcs={"adapter": "git", "source": {"before": HASH}}),
    lineage(
        vcs={
            "adapter": "git",
            "branch": "main",
            "source": {"path": "/abs/x.yaml", "after": HASH},
        }
    ),
    lineage(
        vcs={
            "adapter": "git",
            "branch": "main",
            "source": {"path": "a\\b.yaml", "after": HASH},
        }
    ),
    lineage(
        vcs={
            "adapter": "git",
            "branch": "main",
            "source": {"path": "../x.yaml", "after": HASH},
        }
    ),
    lineage(
        vcs={
            "adapter": "git",
            "branch": "main",
            "source": {"path": "C:x.yaml", "after": HASH},
        }
    ),
    lineage(
        vcs={
            "adapter": "git",
            "branch": "main",
            "source": {"path": "x.yaml", "before": "md5:abc", "after": HASH},
        }
    ),
]


INVALID += [
    lineage(stage=None),
    lineage(stage={**ENFORCED, "allowedBy": None}),
    lineage(stage={**UNENFORCED_LOCAL, "allowedBy": None}),
    lineage(stage=without(UNENFORCED_LOCAL, "allowedBy")),
    lineage(stage={**ENFORCED, "allowedBy": UNENFORCED_LOCAL["allowedBy"]}),
    lineage(stage={**ENFORCED, "effects": "partly"}),
    lineage(stage={**ENFORCED, "name": "Local Stage"}),
    lineage(stage={**UNENFORCED_LOCAL, "allowedBy": {"setting": "x"}}),
    lineage(stage={**UNENFORCED_LOCAL, "allowedBy": {"setting": "Allow", "source": "env"}}),
    lineage(stage={**UNENFORCED_LOCAL, "allowedBy": {"setting": "x", "source": ""}}),
    lineage(stage="local"),
]


@pytest.mark.parametrize("data", INVALID)
def test_the_hand_written_check_refuses_exactly_what_the_schema_refuses(
    data: dict[str, Any],
) -> None:
    assert not is_valid(data, "lineage.schema.json")
    assert lineage_problem(data) is not None


@pytest.mark.parametrize(
    ("data", "field"),
    [
        pytest.param(lineage(reason=None), "reason", id="reason"),
        pytest.param(lineage(stage=None), "stage", id="stage"),
        pytest.param(lineage(stage={**ENFORCED, "allowedBy": None}), "stage", id="allowedBy"),
        pytest.param(lineage(vcs={"adapter": "git", "branch": None}), "vcs.branch", id="branch"),
        pytest.param(lineage(vcs={"adapter": "git", "head": None}), "vcs.head", id="head"),
        pytest.param(lineage(vcs={"adapter": "git", "source": None}), "vcs.source", id="source"),
        pytest.param(
            lineage(vcs={"adapter": "git", "source": {"path": "x", "before": None}}),
            "vcs.source.before",
            id="before",
        ),
        pytest.param(
            lineage(vcs={"adapter": "git", "source": {"path": "x", "after": None}}),
            "vcs.source.after",
            id="after",
        ),
    ],
)
def test_a_null_where_a_field_should_be_left_out_is_refused_naming_the_field(
    data: dict[str, Any], field: str
) -> None:
    assert not is_valid(data, "lineage.schema.json")
    assert field in (lineage_problem(data) or "")


def test_a_lineage_with_nothing_optional_to_say_leaves_those_fields_out() -> None:
    change = new_ulid()
    data = Lineage(
        actor=ACTORS[0],
        via="file",
        at=timestamp(datetime(2026, 10, 12, tzinfo=UTC)),
        reason=None,
        change=change,
        cause=CommandCause(change),
        vcs=VcsState(adapter="files", branch=None, head=None),
    ).to_data()
    assert "reason" not in data
    assert "stage" not in data
    assert data["vcs"] == {"adapter": "files"}
    assert is_valid(data, "lineage.schema.json")
    assert lineage_problem(data) is None


@pytest.mark.parametrize(
    ("vcs", "expected"),
    [
        pytest.param(
            VcsState(adapter="git", branch=None, head="a" * 40),
            {"adapter": "git", "head": "a" * 40},
            id="detached HEAD",
        ),
        pytest.param(
            VcsState(adapter="git", branch="main", head=None),
            {"adapter": "git", "branch": "main"},
            id="no commit yet",
        ),
        pytest.param(
            VcsState(adapter="git", branch="main", head="a" * 40, source=SOURCES[2]),
            {
                "adapter": "git",
                "branch": "main",
                "head": "a" * 40,
                "source": {"path": "new.yaml", "after": HASH},
            },
            id="new file",
        ),
        pytest.param(
            VcsState(adapter="git", branch="main", head="a" * 40, source=SOURCES[3]),
            {
                "adapter": "git",
                "branch": "main",
                "head": "a" * 40,
                "source": {"path": "gone.yaml", "before": HASH},
            },
            id="deleted file",
        ),
    ],
)
def test_version_control_state_leaves_out_what_there_isnt(
    vcs: VcsState, expected: dict[str, Any]
) -> None:
    assert vcs.to_data() == expected


def test_an_enforced_stage_has_no_allowance_field() -> None:
    data = StageLineage(name="docker", effects="enforced", allowed_by=None).to_data()
    assert data == {"name": "docker", "effects": "enforced"}


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


@pytest.mark.parametrize(
    ("effects", "allowed_by"),
    [("unenforced", None), ("enforced", Allowance(setting="x", source="env"))],
)
def test_a_stage_record_names_an_allowance_exactly_when_effects_are_unenforced(
    effects: str, allowed_by: Allowance | None
) -> None:
    with pytest.raises(ValueError, match="names what allowed it"):
        StageLineage(name="local", effects=effects, allowed_by=allowed_by)  # type: ignore[arg-type]


def test_the_hand_written_check_names_the_stage_when_it_is_at_fault() -> None:
    problem = lineage_problem(lineage(stage={**UNENFORCED_LOCAL, "allowedBy": None}))
    assert "stage.allowedBy" in (problem or "")


def test_a_year_before_1000_is_written_with_four_digits_on_every_platform() -> None:
    assert timestamp(datetime(999, 1, 2, 3, 4, 5, 6000, tzinfo=UTC)) == "0999-01-02T03:04:05.006Z"
