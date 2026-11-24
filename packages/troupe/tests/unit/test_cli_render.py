"""One line per run event in troupe logs (spec: cli, "Status and logs commands"), and a run's
tokens and cost in status and logs (spec: cli, "Status shows a run's tokens and cost" and the
requirements after it; run-usage-display design, the approved look)."""

import copy
import json
from typing import Any

import pytest

from runner_schemas import RUNNER_SCHEMAS, load
from troupe.cli.render import render_event, render_run, render_run_line
from troupe.core.client import messages as m

AT = "2026-11-07T00:00:00Z"


def _logged(event: dict[str, object]) -> dict[str, object]:
    return {"seq": 1, "at": AT, "event": event}


def test_a_served_model_line_names_the_model() -> None:
    line = render_event(_logged({"type": "served_model", "model": "gpt-6-luna-2026-03-05"}))
    assert line == f"     1 {AT} served_model: gpt-6-luna-2026-03-05"


def test_a_result_line_names_its_reason_and_why_it_wasnt_retried() -> None:
    event: dict[str, object] = {
        "type": "result",
        "status": "error",
        "reason": "network",
        "notRetried": "side-effect",
        "message": "the connection dropped",
    }
    line = render_event(_logged(event))
    assert (
        line
        == f"     1 {AT} result: error (network, not retried: side-effect): the connection dropped"
    )


def test_a_result_line_without_not_retried_names_only_its_reason() -> None:
    event: dict[str, object] = {
        "type": "result",
        "status": "error",
        "reason": "network",
        "message": "gave up",
    }
    assert render_event(_logged(event)) == f"     1 {AT} result: error (network): gave up"


def _host_event_types() -> list[str]:
    defs = load(RUNNER_SCHEMAS / "run-event.schema.json")["$defs"]
    return [ref["$ref"].rsplit("/", 1)[1] for ref in defs["hostEvent"]["oneOf"]]


@pytest.mark.parametrize("type_", _host_event_types())
def test_every_host_event_type_has_a_summary_after_its_type(type_: str) -> None:
    line = render_event(_logged({"type": type_}))
    assert not line.endswith(f"{type_}:"), json.dumps(line)


# A run's tokens and cost (run-usage-display). The expected lines are the ones the owner approved
# on 2026-11-21, in the design.

USAGE = {
    "inputTokens": 1204,
    "outputTokens": 9817,
    "cacheReadTokens": 182330,
    "cacheWriteTokens": 14022,
}
ESTIMATED_USAGE = {
    "inputTokens": 3410,
    "outputTokens": 2066,
    "cacheReadTokens": 21504,
    "cacheWriteTokens": 0,
}
RUN_ID = "0193a4c2-7f1e-7b55-9c1d-2a6f0e3b8d41"
SUMMARY: dict[str, Any] = {
    "runId": RUN_ID,
    "actor": "tester",
    "startedBy": {"kind": "unknown"},
    "runner": {"requested": "scripted"},
    "stage": {
        "name": "local",
        "effects": "unenforced",
        "allowedBy": {"setting": "allow_unenforced_local_stage", "source": "env"},
    },
    "effectCheck": {"kind": "none"},
    "workspace": {"kind": "theatre"},
    "state": "ended",
    "outcome": "succeeded",
    "events": 42,
    "startedAt": "2026-11-21T09:14:02.000Z",
    "endedAt": "2026-11-21T09:16:40.000Z",
    "transcript": "sha256:" + "a" * 64,
    "transcriptFormat": "native",
    "audit": {"outside": []},
}


def _summary(**fields: Any) -> dict[str, Any]:  # noqa: ANN401
    data = {**copy.deepcopy(SUMMARY), **fields}
    m.RunSummary.from_data(data)  # a shape troupe sends
    return data


def _after_events(lines: list[str]) -> list[str]:
    """The lines between a run summary's events line and its audit, which comes next."""
    start = lines.index("  events: 42") + 1
    end = lines.index("  audit: every change the run made was declared")
    return lines[start:end]


def test_status_of_a_run_whose_service_reported_its_cost() -> None:
    lines = render_run(_summary(usage=USAGE, cost={"usd": 0.4213, "kind": "reported"}))
    assert _after_events(lines) == [
        "  tokens: 1,204 input, 9,817 output, 182,330 cache read, 14,022 cache write",
        "  cost: $0.4213, reported by the service",
    ]


def test_status_of_a_run_whose_cost_was_estimated() -> None:
    lines = render_run(_summary(usage=ESTIMATED_USAGE, cost={"usd": 0.0136, "kind": "estimated"}))
    assert _after_events(lines) == [
        "  tokens: 3,410 input, 2,066 output, 21,504 cache read, 0 cache write",
        "  cost: ~$0.0136, estimated from the runtime's price",
    ]


def test_status_of_a_run_whose_runner_reported_neither() -> None:
    lines = render_run(_summary())
    assert _after_events(lines) == []
    assert not any(line.startswith(("  tokens:", "  cost:")) for line in lines)


def test_status_of_a_run_with_tokens_and_no_price() -> None:
    lines = render_run(_summary(usage=ESTIMATED_USAGE))
    assert _after_events(lines) == [
        "  tokens: 3,410 input, 2,066 output, 21,504 cache read, 0 cache write"
    ]


def test_a_counter_the_runner_left_out_is_left_out_of_the_line_never_shown_as_zero() -> None:
    usage = {key: value for key, value in USAGE.items() if key != "cacheWriteTokens"}
    lines = render_run(_summary(usage=usage))
    assert _after_events(lines) == ["  tokens: 1,204 input, 9,817 output, 182,330 cache read"]


@pytest.mark.parametrize(
    ("cost", "shown"),
    [
        (
            {"usd": 0.00003, "kind": "estimated"},
            "~under $0.0001, estimated from the runtime's price",
        ),
        ({"usd": 0.00003, "kind": "reported"}, "under $0.0001, reported by the service"),
        ({"usd": 0, "kind": "reported"}, "$0, reported by the service"),
        ({"usd": 0, "kind": "estimated"}, "~$0, estimated from the runtime's price"),
        ({"usd": 0.123456, "kind": "reported"}, "$0.1235, reported by the service"),
        ({"usd": 0.00005, "kind": "reported"}, "$0.0001, reported by the service"),
        ({"usd": 12.5, "kind": "reported"}, "$12.5000, reported by the service"),
    ],
    ids=[
        "a tiny estimate",
        "a tiny reported cost",
        "zero",
        "a zero estimate",
        "rounding",
        "half rounds up",
        "dollars",
    ],
)
def test_a_cost_is_shown_to_four_places_never_as_a_false_zero(
    cost: dict[str, Any], shown: str
) -> None:
    assert f"  cost: {shown}" in render_run(_summary(cost=cost))


@pytest.mark.parametrize(
    ("fields", "ending"),
    [
        ({"cost": {"usd": 0.4213, "kind": "reported"}}, "  42 events, $0.4213"),
        (
            {"cost": {"usd": 0.0136, "kind": "estimated"}, "events": 17},
            "  17 events, ~$0.0136 estimated",
        ),
        ({"events": 17}, "  17 events"),
        ({"usage": USAGE, "events": 17}, "  17 events"),
    ],
    ids=["reported", "estimated", "neither", "tokens only"],
)
def test_the_list_of_runs_ends_each_line_with_its_cost(fields: dict[str, Any], ending: str) -> None:
    line = render_run_line(_summary(**fields))
    assert line.endswith(ending)
    assert "tokens" not in line


def test_the_list_line_of_a_run_with_notices_and_a_cost() -> None:
    notice = {
        "at": "2026-11-21T09:15:00.000Z",
        "notice": {"code": "run.silent", "problem": "p", "fix": "f"},
    }
    line = render_run_line(
        _summary(notices=[notice, notice], cost={"usd": 0.4213, "kind": "reported"})
    )
    assert line.endswith("42 events, 2 notices, $0.4213")


def _result(**fields: Any) -> dict[str, Any]:  # noqa: ANN401
    return {
        "seq": 41,
        "at": "2026-11-21T09:16:39Z",
        "event": {"type": "result", "status": "ok", **fields},
    }


def test_a_result_line_with_a_reported_cost() -> None:
    line = render_event(_result(message="All 18 tests pass.", usage=USAGE, costUsd=0.4213))
    assert line == (
        "    41 2026-11-21T09:16:39Z result: ok: All 18 tests pass. (tokens 1,204 in, 9,817 out, "
        "182,330 cache read, 14,022 cache write; cost $0.4213, reported)"
    )


def test_a_result_line_with_an_estimated_cost() -> None:
    line = render_event(
        _result(message="Reviewed 3 files.", usage=ESTIMATED_USAGE, estimatedCostUsd=0.0136)
    )
    assert line.endswith(
        "result: ok: Reviewed 3 files. (tokens 3,410 in, 2,066 out, 21,504 cache read, "
        "0 cache write; cost ~$0.0136, estimated)"
    )


def test_a_result_line_with_neither_ends_with_its_message() -> None:
    assert render_event(_result(message="Reviewed 3 files.")).endswith(
        "result: ok: Reviewed 3 files."
    )


def test_a_result_line_with_tokens_and_no_cost() -> None:
    line = render_event(_result(message="m", usage={"inputTokens": 3, "outputTokens": 4}))
    assert line.endswith("result: ok: m (tokens 3 in, 4 out)")


def test_a_result_line_with_a_cost_and_no_tokens() -> None:
    line = render_event(_result(message="m", estimatedCostUsd=0.00003))
    assert line.endswith("result: ok: m (cost ~under $0.0001, estimated)")


def test_a_failed_result_line_keeps_its_reason_before_the_figures() -> None:
    line = render_event(
        _result(status="error", reason="budget", message="spent", usage={"outputTokens": 9000})
    )
    assert line.endswith("result: error (budget): spent (tokens 9,000 out)")
