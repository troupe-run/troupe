"""The lineage and event-record schemas accept what they should and refuse what they shouldn't
(spec: lineage, event-store; event-store design D3, D8)."""

import copy
from typing import Any

import jsonschema
import pytest

from event_schemas import (
    AT,
    ENFORCED,
    FILES,
    HASH,
    LINEAGE,
    OTHER_HASH,
    ULID,
    UNENFORCED_LOCAL,
    is_valid,
    lineage,
    load,
    without,
)

EVENT: dict[str, Any] = {
    "format": 1,
    "id": HASH,
    "stream": "6c1e2a3b-0000-4000-8000-000000000001",
    "stream_type": "uuid",
    "version": 1,
    "topic": "tests:Thing.Created",
    "parents": [],
    "state": {"lineage": LINEAGE, "timestamp": AT, "name": "x"},
    "batch": {"id": ULID, "index": 0, "size": 1},
}


@pytest.mark.parametrize("name", FILES)
def test_each_schema_is_a_valid_draft_2020_12_schema(name: str) -> None:
    jsonschema.Draft202012Validator.check_schema(load(name))


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(LINEAGE, id="human from the vcs source"),
        pytest.param(
            lineage(actor={"kind": "agent", "id": "tester", "source": "troupe"}, via="runner"),
            id="agent",
        ),
        pytest.param(
            lineage(
                actor={"kind": "unknown"},
                via="file",
                vcs={
                    "adapter": "git",
                    "branch": "main",
                    "head": None,
                    "source": {"path": "actors/tester.yaml", "before": HASH, "after": OTHER_HASH},
                },
            ),
            id="unknown actor from a file edit",
        ),
        pytest.param(lineage(cause={"kind": "event", "id": HASH}), id="event cause"),
        pytest.param(lineage(reason="tidy up"), id="a reason"),
        pytest.param(
            lineage(vcs={"adapter": "files", "branch": None, "head": None, "source": None}),
            id="no version control",
        ),
        pytest.param(
            lineage(approvals=[{"actor": LINEAGE["actor"], "role": "owner", "at": AT}]),
            id="an approval",
        ),
        pytest.param(
            lineage(
                vcs={
                    "adapter": "git",
                    "branch": "main",
                    "head": None,
                    "source": {"path": "new.yaml", "before": None, "after": HASH},
                }
            ),
            id="a file that didn't exist before",
        ),
        pytest.param(
            lineage(
                actor={"kind": "agent", "id": "tester", "source": "troupe"},
                via="runner",
                stage=UNENFORCED_LOCAL,
            ),
            id="a run on a stage that doesn't enforce effects, and what allowed it",
        ),
        pytest.param(lineage(stage=ENFORCED), id="a run on a stage that enforces effects"),
    ],
)
def test_lineage_the_schema_accepts(value: dict[str, Any]) -> None:
    assert is_valid(value, "lineage.schema.json")


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(lineage(actor=None), id="null actor"),
        pytest.param(without(LINEAGE, "actor"), id="missing actor"),
        pytest.param(lineage(actor={"kind": "unknown", "id": "ada"}), id="unknown with an id"),
        pytest.param(lineage(actor={"kind": "human", "id": "", "source": "env"}), id="empty id"),
        pytest.param(lineage(actor={"kind": "human", "id": "ada"}), id="human without a source"),
        pytest.param(lineage(colour="blue"), id="an extra field"),
        pytest.param(lineage(via="email"), id="a via outside the closed set"),
        pytest.param(lineage(at="2026-10-12T03:04:05+10:00"), id="a time not in UTC"),
        pytest.param(lineage(at=float("nan")), id="NaN time"),
        pytest.param(without(LINEAGE, "reason"), id="missing reason"),
        pytest.param(lineage(cause=None), id="null cause"),
        pytest.param(without(LINEAGE, "cause"), id="missing cause"),
        pytest.param(lineage(cause={"kind": "timer", "id": ULID}), id="unknown cause kind"),
        pytest.param(lineage(cause={"kind": "event", "id": ULID}), id="event cause not a hash"),
        pytest.param(lineage(cause={"kind": "command", "id": HASH}), id="command cause not a ULID"),
        pytest.param(lineage(change="not-a-ulid"), id="change not a ULID"),
        pytest.param(
            lineage(
                vcs={
                    "adapter": "git",
                    "branch": "main",
                    "head": None,
                    "source": {"path": "/home/ada/theatre/x.yaml", "before": None, "after": HASH},
                }
            ),
            id="an absolute host path",
        ),
        pytest.param(
            lineage(
                vcs={
                    "adapter": "git",
                    "branch": "main",
                    "head": None,
                    "source": {"path": "actors\\tester.yaml", "before": None, "after": HASH},
                }
            ),
            id="a backslash path",
        ),
        pytest.param(
            lineage(
                vcs={
                    "adapter": "git",
                    "branch": "main",
                    "head": None,
                    "source": {"path": "../outside.yaml", "before": None, "after": HASH},
                }
            ),
            id="a path outside the theatre",
        ),
        pytest.param(
            lineage(
                vcs={
                    "adapter": "git",
                    "branch": "main",
                    "head": None,
                    "source": {"path": "x.yaml", "before": "md5:abc", "after": HASH},
                }
            ),
            id="a hash that isn't sha256",
        ),
        pytest.param(without(LINEAGE, "stage"), id="missing stage"),
        pytest.param(
            lineage(stage={**UNENFORCED_LOCAL, "allowedBy": None}),
            id="an unenforced stage that names nothing that allowed it",
        ),
        pytest.param(
            lineage(stage={**ENFORCED, "allowedBy": UNENFORCED_LOCAL["allowedBy"]}),
            id="an enforced stage that names an allowance",
        ),
        pytest.param(lineage(stage={**ENFORCED, "effects": "partly"}), id="unknown effects"),
        pytest.param(
            lineage(stage={**ENFORCED, "name": "Local Stage"}), id="a stage name with spaces"
        ),
        pytest.param(
            lineage(stage={**UNENFORCED_LOCAL, "allowedBy": {"setting": "x"}}),
            id="an allowance without its source",
        ),
    ],
)
def test_lineage_the_schema_refuses(value: dict[str, Any]) -> None:
    assert not is_valid(value, "lineage.schema.json")


def test_a_header_line_and_an_event_line_are_both_records() -> None:
    header = {"format": 1, "segment": {"session": ULID, "vcs": "git", "branch": "main"}}
    assert is_valid(header, "event-record.schema.json")
    assert is_valid(EVENT, "event-record.schema.json")


def test_an_event_troupe_recorded_must_carry_valid_lineage() -> None:
    assert is_valid(EVENT, "event-record.schema.json#/$defs/troupeEvent")
    bare = copy.deepcopy(EVENT)
    del bare["state"]["lineage"]
    assert not is_valid(bare, "event-record.schema.json#/$defs/troupeEvent")
    bad = copy.deepcopy(EVENT)
    bad["state"]["lineage"]["actor"] = None
    assert not is_valid(bad, "event-record.schema.json#/$defs/troupeEvent")


def test_a_library_event_without_lineage_is_still_a_record() -> None:
    raw = without(EVENT, "state") | {"state_b64": "c3RhdGUx"}
    assert is_valid(raw, "event-record.schema.json")


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"format": 2}, id="an unknown format"),
        pytest.param({"version": float("nan")}, id="NaN version"),
        pytest.param({"version": float("inf")}, id="infinite version"),
        pytest.param({"state_b64": "c3RhdGUx"}, id="both state and state_b64"),
        pytest.param({"parents": [HASH, HASH]}, id="a repeated parent"),
        pytest.param({"stream_type": "int"}, id="an unknown stream type"),
        pytest.param({"batch": {"id": ULID, "index": 0, "size": 0}}, id="an empty batch"),
        pytest.param({"id": "sha1:" + "a" * 40}, id="an id that isn't sha256"),
        pytest.param({"colour": "blue"}, id="an extra field"),
    ],
)
def test_event_records_the_schema_refuses(change: dict[str, Any]) -> None:
    assert not is_valid(EVENT | change, "event-record.schema.json")
