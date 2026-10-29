"""The client protocol's types agree with its schemas, and read requests strictly (spec:
client-protocol; perform-status-logs design D2).

Like the runner contract's types (test_runner_protocol_types.py), messages are generated from
hand-written strategies of the schemas' shapes. Each generated message is first checked against its
schema, so the property covers exactly what the schema accepts that the strategies reach.
"""

import copy
import re
from datetime import UTC, datetime
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from client_schemas import check
from troupe.core.client import messages as m
from troupe.core.events.lineage import timestamp
from troupe.core.messages import Message, ProtocolError

RUN_IDS = st.uuids().map(str)
NAMES = st.from_regex(r"\A[a-z][a-z0-9-]{0,10}\Z")
TEXT = st.text(min_size=1, max_size=20)
TIMES = st.datetimes(
    min_value=datetime(1, 1, 2), max_value=datetime(9999, 12, 30), timezones=st.just(UTC)
).map(timestamp)
HASHES = st.binary(min_size=32, max_size=32).map(lambda b: "sha256:" + b.hex())
PATHS = st.lists(st.from_regex(r"\A[a-z][a-z0-9_.-]{0,8}\Z"), min_size=1, max_size=3).map("/".join)
EFFECT_CHECKS = st.just({"kind": "none"}) | st.fixed_dictionaries(
    {"kind": st.just("files"), "paths": st.lists(PATHS, min_size=1, max_size=3, unique=True)}
)
ERRORS = st.fixed_dictionaries(
    {
        "code": st.just("run.error-result"),
        "problem": TEXT,
        "fix": TEXT,
        "details": st.fixed_dictionaries({"message": TEXT}),
    }
) | st.fixed_dictionaries(
    {
        "code": st.just("runner.crashed"),
        "problem": TEXT,
        "fix": TEXT,
        "details": st.just({"ending": "never-started"})
        | st.fixed_dictionaries(
            {"exitCode": st.integers(-9, 255), "ending": st.sampled_from(["exited", "killed"])}
        ),
    }
)
NOTICES = st.fixed_dictionaries(
    {
        "code": st.just("run.silent"),
        "problem": TEXT,
        "fix": TEXT,
        "details": st.fixed_dictionaries({"seconds": st.integers(0, 600)}),
    }
) | st.fixed_dictionaries(
    {
        "code": st.just("run.retrying"),
        "problem": TEXT,
        "fix": TEXT,
        "details": st.fixed_dictionaries(
            {
                "attempt": st.integers(1, 9),
                "delayMs": st.integers(0, 10**5),
                "reason": st.sampled_from(
                    ["authentication", "rate-limit", "network", "server", "other"]
                ),
            },
            optional={"maxAttempts": st.integers(1, 9)},
        ),
    }
)
ACTORS = st.just({"kind": "unknown"}) | st.fixed_dictionaries(
    {"kind": st.sampled_from(["human", "agent"]), "id": TEXT, "source": NAMES}
)
STAGES = st.just({"name": "docker", "effects": "enforced"}) | st.just(
    {
        "name": "local",
        "effects": "unenforced",
        "allowedBy": {"setting": "allow_unenforced_local_stage", "source": "env"},
    }
)
COMMITS = st.text("0123456789abcdef", min_size=40, max_size=40)
WORKSPACES = st.just({"kind": "theatre"}) | st.fixed_dictionaries(
    {
        "kind": st.just("worktree"),
        "path": st.just(".troupe/local/worktrees/0f8fad5b-d9cb-469f-a165-70867728950e"),
        "base": COMMITS,
        "dirty": st.booleans(),
    },
    optional={
        "prefix": st.sampled_from(["apps/", "apps/web/"]),
        # Absent until the worktree is made (account-for-every-worktree design D4).
        "clones": st.lists(
            st.sampled_from(["clonefile", "ficlone", "copyfile2", "copy", "symlink"]),
            unique=True,
        ),
    },
)
SHARED_LISTS = st.lists(
    st.fixed_dictionaries(
        {"name": TEXT, "change": st.sampled_from(["added", "changed", "removed"])}
    ),
    min_size=1,
    max_size=3,
)
SHARED = st.fixed_dictionaries(
    {}, optional={"refs": SHARED_LISTS, "config": SHARED_LISTS, "hooks": SHARED_LISTS}
).filter(bool)


@st.composite
def run_changes(draw: st.DrawFn) -> dict[str, Any]:
    """A worktree run's changes, in each state, with what that state has."""
    state = draw(st.sampled_from(["pending", "accepted", "discarded", "none", "uncaptured"]))
    data: dict[str, Any] = {"state": state}
    counts = {"added": 0, "modified": 0, "deleted": 0, "leftOut": draw(st.integers(0, 9))}
    if state == "uncaptured":
        if draw(st.booleans()):
            data["error"] = draw(ERRORS)
    elif state == "none":
        data.update(counts)
    else:
        data.update(counts, added=draw(st.integers(1, 9)), diff=draw(HASHES))
    if draw(st.booleans()):
        data["shared"] = draw(SHARED)
    if state in ("accepted", "discarded"):
        data["settledAt"] = draw(TIMES)
    else:
        data["worktree"] = ".troupe/local/worktrees/0f8fad5b-d9cb-469f-a165-70867728950e"
    return data


RUN_CHANGES = run_changes()
OUTCOMES = st.sampled_from(
    ["succeeded", "failed", "cancelled", "timed-out", "crashed", "could-not-start"]
)


@st.composite
def summaries(draw: st.DrawFn) -> dict[str, Any]:
    """A run summary: an ended run has an outcome and an end time, and only an ended one does;
    every other optional field may be absent (omit-nulls design D3)."""
    summary = draw(
        st.fixed_dictionaries(
            {
                "runId": RUN_IDS,
                "actor": NAMES,
                "startedBy": ACTORS,
                "runner": st.fixed_dictionaries(
                    {"requested": NAMES},
                    optional={"reported": st.fixed_dictionaries({"name": TEXT, "version": TEXT})},
                ),
                "stage": STAGES,
                "effectCheck": EFFECT_CHECKS,
                "workspace": WORKSPACES,
                "state": st.sampled_from(
                    ["running", "ended", "interrupted", "unfinished-elsewhere"]
                ),
                "events": st.integers(0, 10**6),
                "startedAt": TIMES,
            },
            optional={
                "error": ERRORS,
                "transcript": HASHES,
                "stderr": HASHES,
                "recording": st.fixed_dictionaries(
                    {"failedAt": st.integers(0, 99), "error": ERRORS}
                ),
            },
        )
    )
    if summary["state"] == "ended":
        summary["outcome"] = draw(OUTCOMES)
        summary["endedAt"] = draw(TIMES)
    if summary["workspace"] != {"kind": "theatre"}:
        summary["changes"] = draw(RUN_CHANGES)
    return summary


SUMMARIES = summaries()


@st.composite
def logged_events(draw: st.DrawFn) -> dict[str, Any]:
    run_id, seq = draw(RUN_IDS), draw(st.integers(0, 10**6))
    event: dict[str, Any] = draw(
        st.sampled_from(
            [
                {"type": "turn", "role": "assistant", "text": "hi"},
                {"type": "log", "level": "info", "message": "m"},
                {"type": "result", "status": "ok", "message": "done"},
                {
                    "type": "oversized",
                    "originalType": "turn",
                    "bytes": 70000,
                    "ref": "sha256:" + "a" * 64,
                },
            ]
        )
    )
    return {
        "kind": "event",
        "runId": run_id,
        "seq": seq,
        "at": draw(TIMES),
        "event": {"runId": run_id, "seq": seq, **event},
    }


NOTICE_UPDATES = st.fixed_dictionaries({"kind": st.just("notice"), "notice": NOTICES})
CASES: list[tuple[object, str, st.SearchStrategy[Any]]] = [
    (
        m.PerformRequest,
        "perform-request.schema.json",
        st.fixed_dictionaries(
            {"actor": NAMES},
            optional={"direction": st.text(max_size=20), "rehearse": st.booleans()},
        ),
    ),
    (
        m.PerformUpdate,
        "perform-update.schema.json",
        st.fixed_dictionaries(
            {"kind": st.just("started"), "runId": RUN_IDS},
            optional={"worktree": st.just(".troupe/local/worktrees/0f8fad5b")},
        )
        | logged_events()
        | NOTICE_UPDATES,
    ),
    (m.PerformResult, "perform-result.schema.json", st.fixed_dictionaries({"run": SUMMARIES})),
    (
        m.StatusRequest,
        "status-request.schema.json",
        st.just({})
        | st.fixed_dictionaries({"limit": st.integers(1, 10000)})
        | st.fixed_dictionaries({"run": RUN_IDS}),
    ),
    (
        m.StatusResult,
        "status-result.schema.json",
        st.fixed_dictionaries(
            {"runs": st.lists(SUMMARIES, max_size=2), "notices": st.lists(NOTICES, max_size=2)}
        ),
    ),
    (
        m.LogsRequest,
        "logs-request.schema.json",
        st.fixed_dictionaries({"run": RUN_IDS}, optional={"follow": st.booleans()}),
    ),
    (m.LogsUpdate, "logs-update.schema.json", logged_events() | NOTICE_UPDATES),
    (
        m.LogsResult,
        "logs-result.schema.json",
        st.fixed_dictionaries(
            {
                "run": SUMMARIES,
                "events": st.lists(logged_events(), max_size=2),
                "notices": st.lists(NOTICES, max_size=2),
            }
        ),
    ),
]


# Config's messages (config-model design D10).

KEYS = st.text(min_size=1, max_size=6)
CONFIG_PATHS = st.lists(KEYS, min_size=1, max_size=3)
JSON = st.recursive(
    st.booleans() | st.integers() | st.text(max_size=6),
    lambda inner: st.lists(inner, max_size=3) | st.dictionaries(KEYS, inner, max_size=3),
    max_leaves=6,
)
VALUES = st.booleans() | st.integers() | st.text(max_size=6) | st.lists(JSON, max_size=3)
ULIDS = st.from_regex(r"\A[0-9A-HJKMNP-TV-Z]{26}\Z")
ENTRIES = st.fixed_dictionaries(
    {"path": CONFIG_PATHS}, optional={"before": HASHES, "after": VALUES}
).filter(lambda e: "before" in e or "after" in e)
FILES = st.fixed_dictionaries(
    {
        "path": st.sampled_from([".troupe/actors/tester.yaml", ".troupe/actors/tester.md"]),
        "action": st.sampled_from(["write", "remove", "finish", "discard"]),
        "reason": st.text(min_size=1, max_size=10),
    },
    optional={"kept": HASHES},
)
CHANGES = st.fixed_dictionaries(
    {"change": ULIDS, "actor": ACTORS, "at": TIMES, "entries": st.lists(ENTRIES, max_size=2)}
)
CONFLICTS = st.fixed_dictionaries(
    {
        "paths": st.lists(CONFIG_PATHS, min_size=1, max_size=2),
        "changes": st.lists(CHANGES, min_size=2, max_size=3),
    },
    optional={"rule": st.text(min_size=1, max_size=10)},
)
OPERATIONS = st.fixed_dictionaries({"path": CONFIG_PATHS, "value": JSON}) | st.fixed_dictionaries(
    {"path": CONFIG_PATHS, "unset": st.just(True)}
)
CASES += [
    (
        m.ConfigSetRequest,
        "config-set-request.schema.json",
        st.fixed_dictionaries(
            {"operations": st.lists(OPERATIONS, min_size=1, max_size=3)},
            optional={"reason": st.text(min_size=1, max_size=10), "rehearse": st.booleans()},
        ),
    ),
    (m.ConfigUpdate, "config-set-update.schema.json", NOTICE_UPDATES),
    (
        m.ConfigSetResult,
        "config-set-result.schema.json",
        st.fixed_dictionaries(
            {
                "entries": st.lists(ENTRIES, max_size=3),
                "files": st.lists(FILES, max_size=2),
                "notices": st.lists(NOTICES, max_size=2),
            },
            optional={"change": ULIDS},
        ),
    ),
    (
        m.ConfigGetRequest,
        "config-get-request.schema.json",
        st.fixed_dictionaries({}, optional={"path": CONFIG_PATHS}),
    ),
    (
        m.ConfigGetResult,
        "config-get-result.schema.json",
        st.fixed_dictionaries(
            {
                "conflicts": st.lists(CONFLICTS, max_size=2),
                "heads": st.lists(HASHES, max_size=2),
                "notices": st.lists(NOTICES, max_size=2),
            },
            optional={"value": JSON},
        ),
    ),
    (
        m.FlushRequest,
        "flush-request.schema.json",
        st.fixed_dictionaries({}, optional={"force": st.booleans(), "rehearse": st.booleans()}),
    ),
    (m.ConfigUpdate, "flush-update.schema.json", NOTICE_UPDATES),
    (m.DiffRequest, "diff-request.schema.json", st.fixed_dictionaries({"run": RUN_IDS})),
    (
        m.DiffResult,
        "diff-result.schema.json",
        st.fixed_dictionaries(
            {"run": RUN_IDS, "base": COMMITS, "changes": RUN_CHANGES},
        ).flatmap(
            lambda result: (
                st.just(result)
                | st.fixed_dictionaries(
                    {
                        "patch": st.text(max_size=40),
                        "encoding": st.sampled_from(["utf-8", "base64"]),
                    }
                ).map(lambda patch: {**result, **patch})
            )
        ),
    ),
    *(
        (
            request_type,
            f"{name}-request.schema.json",
            st.fixed_dictionaries(
                {"run": RUN_IDS}, optional={"reason": TEXT, "rehearse": st.booleans()}
            ),
        )
        for request_type, name in ((m.AcceptRequest, "accept"), (m.DiscardRequest, "discard"))
    ),
    (
        m.AcceptResult,
        "accept-result.schema.json",
        st.fixed_dictionaries(
            {
                "run": RUN_IDS,
                "files": st.lists(TEXT, min_size=1, max_size=3),
                "rehearsed": st.booleans(),
                "notices": st.lists(NOTICES, max_size=2),
            }
        ),
    ),
    (
        m.DiscardResult,
        "discard-result.schema.json",
        st.fixed_dictionaries(
            {
                "run": RUN_IDS,
                "worktree": st.just(".troupe/local/worktrees/0f8fad5b"),
                "rehearsed": st.booleans(),
                "notices": st.lists(NOTICES, max_size=2),
            }
        ),
    ),
    (
        m.FlushResult,
        "flush-result.schema.json",
        st.fixed_dictionaries(
            {"files": st.lists(FILES, max_size=2), "notices": st.lists(NOTICES, max_size=2)}
        ),
    ),
]


def _parse(kind: object, data: object) -> Message:
    if isinstance(kind, type) and issubclass(kind, Message):
        return kind.from_data(data)
    return m.parse_update(kind, data)


@pytest.mark.parametrize(("kind", "schema", "strategy"), CASES, ids=[c[1] for c in CASES])
def test_messages_the_schema_accepts_parse_and_serialise_back_unchanged(
    kind: object, schema: str, strategy: st.SearchStrategy[Any]
) -> None:
    @settings(max_examples=60, deadline=None)
    @given(strategy)
    def round_trip(data: dict[str, Any]) -> None:
        check(data, schema)
        message = _parse(kind, data)
        assert message.to_data() == data
        check(message.to_data(), schema)

    round_trip()


def _refused(kind: object, data: object) -> str:
    with pytest.raises(ProtocolError) as caught:
        _parse(kind, data)
    return str(caught.value)


PERFORM = {"actor": "tester", "direction": "go"}


@pytest.mark.parametrize(
    ("data", "named"),
    [
        ({**PERFORM, "argv": ["sh"]}, "'argv'"),
        ({**PERFORM, "runner": "scripted"}, "'runner'"),
        ({**PERFORM, "effectCheck": {"kind": "none"}}, "'effectCheck'"),
        ({**PERFORM, "instructions": "x"}, "'instructions'"),
        ({"direction": "x"}, "'actor'"),
        ({**PERFORM, "actor": "Tester"}, "PerformRequest.actor"),
        ({**PERFORM, "direction": 7}, "PerformRequest.direction"),
        ({**PERFORM, "direction": None}, "PerformRequest.direction"),
        ({**PERFORM, "rehearse": "yes"}, "PerformRequest.rehearse"),
    ],
)
def test_a_malformed_perform_request_is_refused_naming_the_field(data: object, named: str) -> None:
    assert named in _refused(m.PerformRequest, data)


@pytest.mark.parametrize(
    ("data", "named"),
    [
        ({"run": "0f8fad5"}, "StatusRequest.run"),
        ({"run": "0f8fad5b", "limit": 2}, "not both"),
        ({"limit": 0}, "StatusRequest.limit"),
        ({"limit": 10001}, "StatusRequest.limit"),
        ({"limit": True}, "StatusRequest.limit"),
        ({"verbose": True}, "'verbose'"),
    ],
)
def test_a_malformed_status_request_is_refused_naming_the_field(data: object, named: str) -> None:
    assert named in _refused(m.StatusRequest, data)


def test_a_logged_event_whose_event_belongs_to_another_seq_is_refused() -> None:
    run_id = "0f8fad5b-d9cb-469f-a165-70867728950e"
    data = {
        "kind": "event",
        "runId": run_id,
        "seq": 1,
        "at": "2026-10-12T03:04:05.678Z",
        "event": {"runId": run_id, "seq": 2, "type": "log", "level": "info", "message": "m"},
    }
    assert "runId and seq" in _refused(m.LogsUpdate, data)


def test_an_unknown_notice_code_is_refused_when_turned_into_a_notice() -> None:
    data = m.NoticeData.from_data({"code": "run.made-up", "problem": "p", "fix": "f"})
    with pytest.raises(ProtocolError, match=r"run\.made-up"):
        data.to_notice()


# A run summary carries what its state knows (spec: client-protocol; omit-nulls design D3).

ENDED_SUMMARY: dict[str, Any] = {
    "runId": "0f8fad5b-d9cb-469f-a165-70867728950e",
    "actor": "tester",
    "startedBy": {"kind": "unknown"},
    "runner": {"requested": "scripted", "reported": {"name": "scripted", "version": "0"}},
    "stage": {"name": "docker", "effects": "enforced"},
    "effectCheck": {"kind": "none"},
    "workspace": {"kind": "theatre"},
    "state": "ended",
    "outcome": "failed",
    "error": {"code": "run.error-result", "problem": "p", "fix": "f", "details": {"message": "m"}},
    "events": 1,
    "startedAt": "2026-10-13T00:00:00.000Z",
    "endedAt": "2026-10-13T00:00:01.000Z",
    "transcript": "sha256:" + "a" * 64,
    "stderr": "sha256:" + "b" * 64,
    "recording": {
        "failedAt": 0,
        "error": {
            "code": "run.error-result",
            "problem": "p",
            "fix": "f",
            "details": {"message": "m"},
        },
    },
}


@pytest.mark.parametrize(
    "field",
    ["outcome", "error", "endedAt", "transcript", "stderr", "recording", "runner.reported"],
)
def test_reading_a_summary_with_a_null_field_fails_naming_the_field(field: str) -> None:
    data = copy.deepcopy(ENDED_SUMMARY)
    if field == "runner.reported":
        data["runner"]["reported"] = None
    else:
        data[field] = None
    with pytest.raises(ProtocolError, match=rf"RunSummary\.{re.escape(field)}"):
        m.RunSummary.from_data(data)


def test_the_stage_s_allowance_null_is_refused_naming_it() -> None:
    data = copy.deepcopy(ENDED_SUMMARY)
    data["stage"]["allowedBy"] = None
    with pytest.raises(ProtocolError, match=r"RunSummary\.stage\.allowedBy"):
        m.RunSummary.from_data(data)


@pytest.mark.parametrize(
    ("changes", "label"),
    [
        ({"state": "interrupted"}, "a run that hasn't ended, with an outcome and end time"),
        ({"endedAt": None}, "an ended run without an end time"),
        ({"outcome": None}, "an ended run without an outcome"),
    ],
)
def test_a_summary_whose_outcome_and_end_disagree_with_its_state_is_refused(
    changes: dict[str, Any], label: str
) -> None:
    data = copy.deepcopy(ENDED_SUMMARY)
    for key, value in changes.items():
        if value is None:
            del data[key]
        else:
            data[key] = value
    with pytest.raises(ProtocolError, match="present exactly when state is ended"):
        m.RunSummary.from_data(data)


def test_a_running_runs_summary_has_no_outcome_or_end_and_round_trips() -> None:
    data = {
        key: value
        for key, value in ENDED_SUMMARY.items()
        if key not in ("outcome", "endedAt", "error", "transcript", "stderr", "recording")
    }
    data["state"] = "running"
    summary = m.RunSummary.from_data(data)
    assert summary.outcome is None
    assert summary.ended_at is None
    assert summary.to_data() == data
    check({"run": data}, "perform-result.schema.json")
