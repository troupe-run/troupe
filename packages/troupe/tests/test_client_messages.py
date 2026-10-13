"""The client protocol's types agree with its schemas, and read requests strictly (spec:
client-protocol; perform-status-logs design D2).

Like the runner contract's types (test_runner_protocol_types.py), messages are generated from
hand-written strategies of the schemas' shapes. Each generated message is first checked against its
schema, so the property covers exactly what the schema accepts that the strategies reach.
"""

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
        "details": st.fixed_dictionaries(
            {
                "exitCode": st.none() | st.integers(-9, 255),
                "ending": st.sampled_from(["exited", "killed", "never-started"]),
            }
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
                "maxAttempts": st.none() | st.integers(1, 9),
                "delayMs": st.integers(0, 10**5),
                "reason": st.sampled_from(
                    ["authentication", "rate-limit", "network", "server", "other"]
                ),
            }
        ),
    }
)
ACTORS = st.just({"kind": "unknown"}) | st.fixed_dictionaries(
    {"kind": st.sampled_from(["human", "agent"]), "id": TEXT, "source": NAMES}
)
STAGES = st.just({"name": "docker", "effects": "enforced", "allowedBy": None}) | st.just(
    {
        "name": "local",
        "effects": "unenforced",
        "allowedBy": {"setting": "allow_unenforced_local_stage", "source": "env"},
    }
)
SUMMARIES = st.fixed_dictionaries(
    {
        "runId": RUN_IDS,
        "actor": NAMES,
        "startedBy": ACTORS,
        "runner": st.fixed_dictionaries(
            {
                "requested": NAMES,
                "reported": st.none() | st.fixed_dictionaries({"name": TEXT, "version": TEXT}),
            }
        ),
        "stage": STAGES,
        "effectCheck": EFFECT_CHECKS,
        "state": st.sampled_from(["running", "ended", "interrupted", "unfinished-elsewhere"]),
        "outcome": st.none()
        | st.sampled_from(
            ["succeeded", "failed", "cancelled", "timed-out", "crashed", "could-not-start"]
        ),
        "error": st.none() | ERRORS,
        "events": st.integers(0, 10**6),
        "startedAt": TIMES,
        "endedAt": st.none() | TIMES,
        "transcript": st.none() | HASHES,
        "stderr": st.none() | HASHES,
        "recording": st.none()
        | st.fixed_dictionaries({"failedAt": st.integers(0, 99), "error": ERRORS}),
    }
)


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
            {"actor": NAMES, "runner": NAMES, "effectCheck": EFFECT_CHECKS},
            optional={
                "options": st.fixed_dictionaries(
                    {"script": st.fixed_dictionaries({"steps": st.just([])})},
                    optional={"replayDelays": st.booleans()},
                ),
                "instructions": st.text(max_size=20),
            },
        ),
    ),
    (
        m.PerformUpdate,
        "perform-update.schema.json",
        st.fixed_dictionaries({"kind": st.just("started"), "runId": RUN_IDS})
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


PERFORM = {"actor": "tester", "runner": "scripted", "effectCheck": {"kind": "none"}}


@pytest.mark.parametrize(
    ("data", "named"),
    [
        ({**PERFORM, "argv": ["sh"]}, "'argv'"),
        ({"actor": "tester", "runner": "scripted"}, "'effectCheck'"),
        ({**PERFORM, "actor": "Tester"}, "PerformRequest.actor"),
        ({**PERFORM, "runner": 7}, "PerformRequest.runner"),
        ({**PERFORM, "options": []}, "PerformRequest.options"),
        ({**PERFORM, "effectCheck": {"kind": "maybe"}}, "PerformRequest.effectCheck"),
        (
            {**PERFORM, "effectCheck": {"kind": "files", "paths": ["../x"]}},
            "PerformRequest.effectCheck.paths[0]",
        ),
        (
            {**PERFORM, "effectCheck": {"kind": "files", "paths": ["/etc/passwd"]}},
            "PerformRequest.effectCheck.paths[0]",
        ),
        (
            {**PERFORM, "effectCheck": {"kind": "files", "paths": ["C:x"]}},
            "PerformRequest.effectCheck.paths[0]",
        ),
        ({**PERFORM, "effectCheck": {"kind": "files", "paths": []}}, "PerformRequest.effectCheck"),
        ({**PERFORM, "instructions": None}, "PerformRequest.instructions"),
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
