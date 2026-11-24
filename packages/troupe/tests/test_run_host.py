"""Tests for the run host, driving real runner processes (spec: actor-runners, runner-protocol).

Its tests that stay in their own process are in unit/test_run_host_unit.py."""

import base64
import dataclasses
import json
import shutil
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import pytest

from protocol_schemas import check_notice, validator_for
from run_host_shared import FAST, STORED_RECORD, Ran, _audit, _code, _run, _states
from runner_schemas import validate
from troupe.core import defaults
from troupe.core.artifacts import MemoryArtifactStore, load_store
from troupe.core.errors import TroupeError
from troupe.core.masking import Masker
from troupe.core.runners import host as host_module
from troupe.core.runners.effects import (
    Change,
    DeclaredEffects,
    ExpectedFiles,
)
from troupe.core.runners.limits import RunLimits
from troupe.core.runners.outcome import Ending, Outcome, TranscriptFormat
from troupe.platform import processes
from troupe_plugin_sdk import runner as p
from troupe_plugin_sdk.effects import Effects

FAKE = Path(__file__).with_name("fake_runner.py")
INIT = {"type": "init", "runner": {"name": "scripted", "version": "0.0.1"}, "tools": ["Write"]}
OK = {"type": "result", "status": "ok", "message": "done"}
ERROR_RESULT = {
    "type": "result",
    "status": "error",
    "reason": "authentication",
    "message": "API Error: 401",
}


def _fake(mode: str) -> list[str]:
    return [sys.executable, str(FAKE), mode]


# Requirement: Every run attempt has exactly one outcome (each one reachable)


def test_a_run_with_an_ok_result_and_a_clean_exit_succeeds(tmp_path: Path) -> None:
    ran = _run(tmp_path, {"steps": [{"event": INIT}, {"event": OK}]})
    assert (ran.outcome.outcome, ran.outcome.error) == (Outcome.SUCCEEDED, None)
    assert ran.types == ["init", "result"]
    assert ran.outcome.exit_code == 0
    assert ran.outcome.ending is Ending.EXITED
    assert [m["method"] for m in ran.sent] == ["initialize", "run/start", "shutdown"]


def test_a_run_with_an_error_result_fails(tmp_path: Path) -> None:
    ran = _run(tmp_path, {"steps": [{"event": INIT}, {"event": ERROR_RESULT}]})
    assert (ran.outcome.outcome, _code(ran)) == (Outcome.FAILED, "run.error-result")
    assert ran.outcome.exit_code == 0


def test_a_run_cancelled_by_its_caller_is_cancelled(tmp_path: Path) -> None:
    ran = _run(tmp_path, {"steps": [{"event": INIT}, {"hang": True}]}, cancel_after=0.5)
    assert (ran.outcome.outcome, ran.outcome.error) == (Outcome.CANCELLED, None)
    assert ran.outcome.ending is Ending.EXITED  # it honoured the cancel; nothing was killed
    assert "run/cancel" in [m["method"] for m in ran.sent]


def test_a_run_past_its_time_limit_is_timed_out_naming_the_limit(tmp_path: Path) -> None:
    ran = _run(
        tmp_path,
        {"steps": [{"event": INIT}, {"hang": True}]},
        limits=RunLimits(run_timeout=0.5, cancel_grace=2.0),
    )
    assert (ran.outcome.outcome, _code(ran)) == (Outcome.TIMED_OUT, "run.timeout")
    assert ran.outcome.error is not None
    assert "0.5s" in ran.outcome.error.problem


def test_a_runner_that_exits_mid_run_has_crashed_and_its_exit_code_is_kept(tmp_path: Path) -> None:
    ran = _run(tmp_path, {"steps": [{"event": INIT}, {"exit": 0}]})
    assert (ran.outcome.outcome, _code(ran)) == (Outcome.CRASHED, "runner.crashed")
    assert ran.outcome.exit_code == 0


# Requirement: Success needs an ok result, a passing effect check and a clean exit


def test_an_ok_result_whose_expected_file_is_missing_fails_naming_it(tmp_path: Path) -> None:
    ran = _run(
        tmp_path,
        {"steps": [{"event": INIT}, {"event": OK}]},
        effect=ExpectedFiles([tmp_path / "out" / "hello.txt"]),
    )
    assert (ran.outcome.outcome, _code(ran)) == (Outcome.FAILED, "run.effect-missing")
    assert ran.outcome.error is not None
    assert ran.outcome.error.path == str(tmp_path / "out" / "hello.txt")


def test_an_ok_result_with_its_expected_file_written_succeeds(tmp_path: Path) -> None:
    ran = _run(
        tmp_path,
        {
            "steps": [
                {"event": INIT},
                {"writeFile": {"path": "out/hello.txt", "content": "hi"}},
                {"event": OK},
            ]
        },
        effect=ExpectedFiles([tmp_path / "out" / "hello.txt"]),
    )
    assert ran.outcome.outcome is Outcome.SUCCEEDED


def test_an_ok_result_followed_by_an_unclean_exit_fails_as_uncertain(tmp_path: Path) -> None:
    ran = _run(tmp_path, {"steps": [{"event": INIT}, {"event": OK}, {"exit": 3}]})
    assert (ran.outcome.outcome, _code(ran)) == (Outcome.FAILED, "run.unclean-exit")
    assert ran.outcome.exit_code == 3


CONTEXT = {"type": "context", "kind": "compacted", "by": "engine", "message": "compacted"}
"""A context event step: the engine compacted and the run carries on (spec: runner-protocol)."""

OTHER_RUN = "11111111-1111-4111-8111-111111111111"
"""A run id for a raw line, which can't carry the run's own: the event is refused for its shape
before its id is read."""

# Requirement: Protocol violations end the run


@pytest.mark.parametrize(
    ("steps", "expected"),
    [
        ([{"rawStdout": "not json at all"}, {"hang": True}], "not JSON"),
        ([{"rawStdout": '{"some": "object"}'}, {"hang": True}], "JSON-RPC 2.0"),
        ([{"event": INIT}, {"event": {**OK, "seq": 3}}, {"hang": True}], "should have been 1"),
        ([{"event": INIT}, {"event": {**OK, "seq": 0}}, {"hang": True}], "should have been 1"),
        ([{"event": {**OK, "seq": 0}}, {"hang": True}], "not 'init'"),
        ([{"event": {**CONTEXT, "seq": 0}}, {"hang": True}], "not 'init'"),
        (
            [
                {"event": INIT},
                {
                    "rawStdout": json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "method": "run/event",
                            "params": {**CONTEXT, "runId": OTHER_RUN, "seq": 1, "kind": "pruned"},
                        }
                    )
                },
                {"hang": True},
            ],
            "pruned",
        ),
        (
            [{"rawStdout": '{"jsonrpc":"2.0","method":"run/pause","params":{}}'}, {"hang": True}],
            "doesn't define",
        ),
        (
            [
                {"event": INIT},
                {
                    "event": {
                        "type": "tool_result",
                        "callId": "c9",
                        "isError": False,
                        "outputSummary": "",
                        "outputBytes": 0,
                    }
                },
                {"hang": True},
            ],
            "no earlier tool_call",
        ),
        (
            [
                {"event": {**INIT, "engine": {"name": "e", "model": "m-1"}}},
                {"event": {"type": "served_model", "model": "m-1"}},
                {"hang": True},
            ],
            "served_model named 'm-1', the model its init named",
        ),
        (
            [
                {"event": INIT},
                {"event": {"type": "served_model", "model": "m-2"}},
                {"event": {"type": "served_model", "model": "m-2"}},
                {"hang": True},
            ],
            "served_model named 'm-2', which an earlier served_model did",
        ),
        (
            [
                {"event": INIT},
                {"transcript": {"record": "not base64!", "encoding": "base64"}},
                {"hang": True},
            ],
            "isn't valid base64",
        ),
        (
            [{"event": {**INIT, "runId": "11111111-1111-4111-8111-111111111111"}}, {"hang": True}],
            "not this run",
        ),
        (
            [
                {"rawStdout": '{"jsonrpc":"2.0","method":"run/event","params":{"seq":0,"seq":1}}'},
                {"hang": True},
            ],
            "ambiguous JSON",
        ),
    ],
    ids=[
        "garbage",
        "not JSON-RPC",
        "seq gap",
        "seq repeat",
        "before init",
        "context before init",
        "context kind of its own",
        "unknown method",
        "tool result without call",
        "served model that is init's",
        "served model twice",
        "invalid base64",
        "other run id",
        "duplicate key",
    ],
)
def test_each_protocol_violation_crashes_the_run_naming_it(
    tmp_path: Path, steps: list[dict[str, Any]], expected: str
) -> None:
    ran = _run(tmp_path, {"onCancel": "ignore", "steps": steps})
    assert (ran.outcome.outcome, _code(ran)) == (Outcome.CRASHED, "runner.protocol")
    assert ran.outcome.error is not None
    assert expected in ran.outcome.error.problem
    assert "line" in ran.outcome.error.problem
    assert ran.outcome.ending is Ending.KILLED


# Requirement: The host drops an estimate it gave no price for (spec: runner-protocol)

ESTIMATE = {**OK, "estimatedCostUsd": 0.5}
UNPRICED = p.RunStartRuntime(
    name="local-ai", endpoint="http://127.0.0.1:1234/v1", model="m", credential=False
)


@pytest.mark.parametrize(
    "runtime",
    [pytest.param(None, id="no runtime"), pytest.param(UNPRICED, id="a runtime with no price")],
)
def test_an_estimate_troupe_gave_no_price_for_is_dropped_with_a_notice_naming_the_runner(
    tmp_path: Path, runtime: p.RunStartRuntime | None
) -> None:
    ran = _run(tmp_path, {"steps": [{"event": INIT}, {"event": ESTIMATE}]}, runtime=runtime)
    assert ran.outcome.outcome is Outcome.SUCCEEDED
    [result] = [e for e in ran.events if isinstance(e, p.ResultEvent)]
    assert result.estimated_cost_usd is None
    assert "estimatedCostUsd" not in result.to_data()
    [notice] = [n for n in ran.notices if n.code == "run.estimate-dropped"]
    assert notice.details == {"runner": "scripted"}
    check_notice(notice.to_data())


def test_an_estimate_troupe_gave_a_price_for_is_recorded_as_sent(tmp_path: Path) -> None:
    priced = dataclasses.replace(UNPRICED, price=p.Price(input=2, output=8))
    ran = _run(tmp_path, {"steps": [{"event": INIT}, {"event": ESTIMATE}]}, runtime=priced)
    assert ran.outcome.outcome is Outcome.SUCCEEDED
    [result] = [e for e in ran.events if isinstance(e, p.ResultEvent)]
    assert result.estimated_cost_usd == 0.5
    assert result.cost_usd is None
    assert not [n for n in ran.notices if n.code == "run.estimate-dropped"]


def test_a_reported_cost_needs_no_price(tmp_path: Path) -> None:
    reported = {**OK, "costUsd": 0.5}
    ran = _run(tmp_path, {"steps": [{"event": INIT}, {"event": reported}]})
    assert ran.outcome.outcome is Outcome.SUCCEEDED


KILL_STATUS = processes.KILLED_EXIT_CODE if sys.platform == "win32" else -9
"""The exit status troupe's kill gives a runner: its named code on Windows, SIGKILL elsewhere."""

# Requirement: An error result names one reason from a closed list


def test_an_error_result_without_a_reason_crashes_the_run_naming_reason(tmp_path: Path) -> None:
    ran = _run(tmp_path, argv=_fake("error-without-reason"))
    assert (ran.outcome.outcome, _code(ran)) == (Outcome.CRASHED, "runner.protocol")
    assert ran.outcome.error is not None
    assert "reason" in ran.outcome.error.problem


def test_an_error_results_reason_reaches_the_outcomes_details(tmp_path: Path) -> None:
    ran = _run(tmp_path, {"steps": [{"event": INIT}, {"event": ERROR_RESULT}]})
    assert (ran.outcome.outcome, _code(ran)) == (Outcome.FAILED, "run.error-result")
    assert ran.outcome.error is not None
    assert ran.outcome.error.details == {"reason": "authentication", "message": "API Error: 401"}


@pytest.mark.parametrize(
    "late",
    [{"type": "log", "level": "info", "message": "late"}, CONTEXT],
    ids=["log", "context"],
)
def test_a_late_event_after_the_result_crashes_the_run_whether_the_runner_answers_shutdown_first(
    tmp_path: Path, late: dict[str, Any]
) -> None:
    # The host sends shutdown on the result, and the hanging runner answers it by exiting 0. That
    # exit and the host's kill for the late event race, so either can end the runner, and the
    # ending must say which did.
    ran = _run(
        tmp_path, {"steps": [{"event": INIT}, {"event": OK}, {"event": late}, {"hang": True}]}
    )
    assert (ran.outcome.outcome, _code(ran)) == (Outcome.CRASHED, "runner.protocol")
    assert ran.outcome.error is not None
    assert "after its result" in ran.outcome.error.problem
    assert "line" in ran.outcome.error.problem
    assert (ran.outcome.ending, ran.outcome.exit_code) in {
        (Ending.KILLED, KILL_STATUS),
        (Ending.EXITED, 0),
    }


def test_nothing_is_written_to_the_transcript_for_an_invalid_base64_record(tmp_path: Path) -> None:
    ran = _run(
        tmp_path,
        {
            "steps": [
                {"event": INIT},
                {"transcript": "kept"},
                {"transcript": {"record": "!!", "encoding": "base64"}},
            ]
        },
    )
    assert ran.transcript() == b"kept\n"


def test_a_message_over_the_maximum_size_is_a_violation_naming_the_limit(tmp_path: Path) -> None:
    ran = _run(
        tmp_path,
        {"steps": [{"event": INIT}, {"transcript": "x" * 5000}, {"hang": True}]},
        limits=RunLimits(max_message_bytes=2048, event_max_bytes=1024, cancel_grace=2.0),
    )
    assert (ran.outcome.outcome, _code(ran)) == (Outcome.CRASHED, "runner.protocol")
    assert ran.outcome.error is not None
    assert "2048" in ran.outcome.error.problem


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("wrong-version", "protocol version 1"),
        ("capability", "must be one of 'transcript-kinds', not 'resume'"),
        ("wrong-run-id", "not this run"),
        ("unsent-id", "never sent"),
    ],
)
def test_answers_that_do_not_match_the_request_are_violations(
    tmp_path: Path, mode: str, expected: str
) -> None:
    ran = _run(tmp_path, argv=_fake(mode))
    assert (ran.outcome.outcome, _code(ran)) == (Outcome.CRASHED, "runner.protocol")
    assert ran.outcome.error is not None
    assert expected in ran.outcome.error.problem


# Requirement: A runner that cannot start is reported


def test_a_runner_that_never_answers_the_handshake_could_not_start(tmp_path: Path) -> None:
    ran = _run(
        tmp_path, argv=_fake("silent"), limits=RunLimits(start_timeout=1.0, cancel_grace=2.0)
    )
    assert (ran.outcome.outcome, _code(ran)) == (Outcome.COULD_NOT_START, "runner.start-timeout")


def test_a_compatible_runner_is_offered_version_1_and_answers_it(tmp_path: Path) -> None:
    ran = _run(tmp_path, {"steps": [{"event": INIT}, {"event": OK}]})
    assert ran.sent[0]["params"]["protocolVersions"] == [0]
    assert ran.sent[0]["params"]["capabilities"] == ["transcript-kinds"]
    assert ran.received[0]["result"]["protocolVersion"] == 0


def test_a_capability_the_contract_defines_but_troupe_didnt_offer_is_a_violation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(host_module, "OFFERED_CAPABILITIES", ())
    ran = _run(tmp_path, argv=_fake("accept-transcript-kinds"))
    assert ran.sent[0]["params"]["capabilities"] == []
    assert (ran.outcome.outcome, _code(ran)) == (Outcome.CRASHED, "runner.protocol")
    assert ran.outcome.error is not None
    assert "capabilities troupe didn't offer (transcript-kinds)" in ran.outcome.error.problem


def test_an_incompatible_runner_could_not_start_and_no_run_is_started(tmp_path: Path) -> None:
    ran = _run(tmp_path, argv=_fake("incompatible"))
    assert (ran.outcome.outcome, _code(ran)) == (Outcome.COULD_NOT_START, "runner.incompatible")
    assert [m["method"] for m in ran.sent] == ["initialize"]


def test_a_runner_that_refuses_run_start_could_not_start_with_its_reason(tmp_path: Path) -> None:
    ran = _run(tmp_path, options={"script": {"steps": []}, "speed": 2}, valid_options=False)
    assert (ran.outcome.outcome, _code(ran)) == (Outcome.COULD_NOT_START, "runner.start-failed")
    assert ran.outcome.error is not None
    assert "'speed'" in ran.outcome.error.problem


# Requirement: Cancelling is graceful, then hard, and always ends


def test_a_runner_ignoring_cancel_is_killed_with_the_process_it_started(tmp_path: Path) -> None:
    ran = _run(
        tmp_path,
        argv=_fake("ignore-cancel-with-child"),
        cancel_after=1.0,
        limits=RunLimits(cancel_grace=1.0),
    )
    assert (ran.outcome.outcome, ran.outcome.ending) == (Outcome.CANCELLED, Ending.KILLED)
    grandchild = int(next(e for e in ran.events if isinstance(e, p.LogEvent)).message)
    deadline = time.monotonic() + 10
    while processes.is_running(grandchild) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not processes.is_running(grandchild)


def test_a_runner_that_ignores_shutdown_after_its_result_is_killed_and_fails_as_uncertain(
    tmp_path: Path,
) -> None:
    ran = _run(tmp_path, argv=_fake("ignore-shutdown"), limits=RunLimits(cancel_grace=1.0))
    assert (ran.outcome.outcome, _code(ran)) == (Outcome.FAILED, "run.unclean-exit")
    assert ran.outcome.ending is Ending.KILLED


# Requirement: Silence and retries are announced; authentication retries fail fast

RETRY = {"type": "retry", "attempt": 1, "maxAttempts": 10, "delayMs": 500}


def test_a_quiet_runner_is_announced_as_silent(tmp_path: Path) -> None:
    ran = _run(
        tmp_path,
        {"steps": [{"event": INIT}, {"wait": {"ms": 800}}, {"event": OK}]},
        limits=RunLimits(silence_announce=0.3, cancel_grace=2.0),
    )
    assert [n.code for n in ran.notices] == ["run.silent"]
    assert ran.outcome.outcome is Outcome.SUCCEEDED


def test_a_retry_is_announced_with_its_attempt_and_reason(tmp_path: Path) -> None:
    ran = _run(
        tmp_path,
        {"steps": [{"event": INIT}, {"event": {**RETRY, "reason": "rate-limit"}}, {"event": OK}]},
    )
    (notice,) = ran.notices
    assert notice.code == "run.retrying"
    assert notice.details["attempt"] == 1
    assert notice.details["maxAttempts"] == 10
    assert notice.details["reason"] == "rate-limit"


def test_a_retry_that_doesnt_say_how_many_attempts_is_announced_without_max_attempts(
    tmp_path: Path,
) -> None:
    retry = {key: value for key, value in RETRY.items() if key != "maxAttempts"}
    ran = _run(
        tmp_path,
        {"steps": [{"event": INIT}, {"event": {**retry, "reason": "network"}}, {"event": OK}]},
    )
    (notice,) = ran.notices
    assert notice.code == "run.retrying"
    assert "maxAttempts" not in notice.details
    assert "attempt 1," in notice.problem


def test_an_authentication_retry_cancels_the_run_at_once_and_fails_it(tmp_path: Path) -> None:
    ran = _run(
        tmp_path,
        {
            "steps": [
                {"event": INIT},
                {"event": {**RETRY, "reason": "authentication"}},
                {"hang": True},
            ]
        },
    )
    assert (ran.outcome.outcome, _code(ran)) == (Outcome.FAILED, "run.authentication")


def test_with_fail_fast_off_an_authentication_retry_lets_the_run_carry_on(tmp_path: Path) -> None:
    ran = _run(
        tmp_path,
        {
            "steps": [
                {"event": INIT},
                {"event": {**RETRY, "reason": "authentication"}},
                {"event": OK},
            ]
        },
        limits=RunLimits(fail_fast_on_auth_retry=False, cancel_grace=2.0),
    )
    assert ran.outcome.outcome is Outcome.SUCCEEDED


def test_a_shorter_run_timeout_from_the_caller_is_the_one_used(tmp_path: Path) -> None:
    started = time.monotonic()
    ran = _run(
        tmp_path,
        {"steps": [{"event": INIT}, {"hang": True}]},
        limits=RunLimits(run_timeout=0.3, cancel_grace=2.0),
    )
    assert ran.outcome.outcome is Outcome.TIMED_OUT
    assert ran.outcome.limits.run_timeout == 0.3
    assert time.monotonic() - started < 15


# Requirement: The transcript is stored and referenced by hash


def test_transcript_records_are_kept_verbatim_in_order_including_base64(tmp_path: Path) -> None:
    raw = b"\x00\xffbinary"
    ran = _run(
        tmp_path,
        {
            "steps": [
                {"event": INIT},
                {"transcript": '{"type":"system","subtype":"init"}'},
                {"transcript": {"record": base64.b64encode(raw).decode(), "encoding": "base64"}},
                {"transcript": "ünïcødé"},
                {"event": OK},
            ]
        },
    )
    assert ran.transcript() == (
        b'{"type":"system","subtype":"init"}\n' + raw + b"\n" + "ünïcødé\n".encode()
    )


def test_a_cancelled_run_keeps_every_transcript_record_received(tmp_path: Path) -> None:
    ran = _run(
        tmp_path,
        {"steps": [{"event": INIT}, {"transcript": "one"}, {"transcript": "two"}, {"hang": True}]},
        cancel_after=0.5,
    )
    assert ran.outcome.outcome is Outcome.CANCELLED
    assert ran.transcript() == b"one\ntwo\n"


def test_a_transcript_past_its_limit_stops_the_run_and_keeps_what_came(tmp_path: Path) -> None:
    ran = _run(
        tmp_path,
        {"steps": [{"event": INIT}] + [{"transcript": "x" * 100}] * 20 + [{"hang": True}]},
        limits=RunLimits(transcript_max_bytes=500, cancel_grace=2.0),
    )
    assert (ran.outcome.outcome, _code(ran)) == (Outcome.FAILED, "run.transcript-too-large")
    assert len(ran.transcript()) > 500


def test_an_oversized_event_is_kept_whole_out_of_line_and_the_run_carries_on(
    tmp_path: Path,
) -> None:
    big = {"type": "tool_call", "callId": "c1", "tool": "Write", "inputSummary": "y" * 3000}
    ran = _run(
        tmp_path,
        {"steps": [{"event": INIT}, {"event": big}, {"event": OK}]},
        limits=RunLimits(event_max_bytes=1024, cancel_grace=2.0),
    )
    assert ran.types == ["init", "oversized", "result"]
    oversized = ran.events[1]
    assert isinstance(oversized, p.OversizedEvent)
    assert (oversized.seq, oversized.original_type) == (1, "tool_call")
    assert oversized.bytes > 1024
    validate(oversized.to_data(), "run-event.schema.json#/$defs/hostEvent")
    stored = json.loads(ran.store.read(oversized.ref))
    assert stored["params"]["inputSummary"] == "y" * 3000
    assert stored == ran.received[3]  # after the two responses and init
    assert ran.outcome.outcome is Outcome.SUCCEEDED


def test_an_oversized_result_with_an_unpriced_estimate_is_stored_without_it(
    tmp_path: Path,
) -> None:
    big = {**ESTIMATE, "message": "z" * 3000}
    ran = _run(
        tmp_path,
        {"steps": [{"event": INIT}, {"event": big}]},
        limits=RunLimits(event_max_bytes=1024, cancel_grace=2.0),
    )
    assert ran.outcome.outcome is Outcome.SUCCEEDED
    oversized = ran.events[1]
    assert isinstance(oversized, p.OversizedEvent)
    assert oversized.original_type == "result"
    stored = json.loads(ran.store.read(oversized.ref))
    assert stored["method"] == "run/event"
    assert stored["params"]["message"] == "z" * 3000
    assert "estimatedCostUsd" not in stored["params"]
    assert "estimatedCostUsd" in ran.received[3]["params"]  # the runner did send it
    assert [n.code for n in ran.notices if n.code == "run.estimate-dropped"] == [
        "run.estimate-dropped"
    ]


def test_served_models_other_than_inits_are_reported_and_the_run_succeeds(tmp_path: Path) -> None:
    init = {**INIT, "engine": {"name": "e", "model": "m-1"}}
    served = [{"event": {"type": "served_model", "model": m}} for m in ("m-2", "m-3")]
    ran = _run(tmp_path, {"steps": [{"event": init}, *served, {"event": OK}]})
    assert ran.types == ["init", "served_model", "served_model", "result"]
    assert [e.model for e in ran.events if isinstance(e, p.ServedModelEvent)] == ["m-2", "m-3"]
    assert ran.outcome.outcome is Outcome.SUCCEEDED


def test_with_no_model_on_init_a_served_model_is_accepted(tmp_path: Path) -> None:
    served = {"event": {"type": "served_model", "model": "m-1"}}
    ran = _run(tmp_path, {"steps": [{"event": INIT}, served, {"event": OK}]})
    assert ran.types == ["init", "served_model", "result"]
    assert ran.outcome.outcome is Outcome.SUCCEEDED


def test_an_oversized_served_model_is_kept_out_of_line(tmp_path: Path) -> None:
    served = {"type": "served_model", "model": "m" * 256}
    ran = _run(
        tmp_path,
        {"steps": [{"event": INIT}, {"event": served}, {"event": OK}]},
        limits=RunLimits(event_max_bytes=200, cancel_grace=2.0),
    )
    assert ran.types == ["init", "oversized", "result"]
    oversized = ran.events[1]
    assert isinstance(oversized, p.OversizedEvent)
    assert oversized.original_type == "served_model"
    validate(oversized.to_data(), "run-event.schema.json#/$defs/hostEvent")
    assert json.loads(ran.store.read(oversized.ref))["params"]["model"] == "m" * 256


def test_an_oversized_context_event_is_kept_whole_out_of_line_and_the_run_carries_on(
    tmp_path: Path,
) -> None:
    big = {**CONTEXT, "message": "z" * 3000, "tokensBefore": 41000}
    ran = _run(
        tmp_path,
        {"steps": [{"event": INIT}, {"event": big}, {"event": OK}]},
        limits=RunLimits(event_max_bytes=1024, cancel_grace=2.0),
    )
    assert ran.types == ["init", "oversized", "result"]
    oversized = ran.events[1]
    assert isinstance(oversized, p.OversizedEvent)
    assert (oversized.seq, oversized.original_type) == (1, "context")
    validate(oversized.to_data(), "run-event.schema.json#/$defs/hostEvent")
    stored = json.loads(ran.store.read(oversized.ref))
    assert stored["params"]["message"] == "z" * 3000
    assert ran.outcome.outcome is Outcome.SUCCEEDED


def test_a_message_larger_than_64_kib_is_received_whole(tmp_path: Path) -> None:
    ran = _run(tmp_path, {"steps": [{"event": INIT}, {"transcript": "z" * 200_000}, {"event": OK}]})
    assert ran.outcome.outcome is Outcome.SUCCEEDED
    assert ran.transcript() == b"z" * 200_000 + b"\n"


def test_standard_error_is_stored_and_kept_to_its_first_and_last_halves(tmp_path: Path) -> None:
    ran = _run(
        tmp_path,
        {"steps": [{"event": INIT}, {"stderr": "A" * 600 + "B" * 600}, {"event": OK}]},
        limits=RunLimits(stderr_max_bytes=200, cancel_grace=2.0),
    )
    kept = ran.stderr()
    assert kept.startswith(b"A" * 100)
    assert kept.endswith(b"B" * 100)
    assert b"[troupe: 1000 bytes of standard error left out]" in kept


def test_the_run_host_stores_its_transcript_in_any_store(tmp_path: Path) -> None:
    for store in (MemoryArtifactStore(), load_store("local", tmp_path / "artifacts")):
        ran = _run(
            tmp_path,
            {"steps": [{"event": INIT}, {"transcript": "kept"}, {"event": OK}]},
            store=store,
        )
        assert ran.transcript() == b"kept\n"


# Requirement: Runners start with an explicit environment; events reach the caller live


def test_a_runner_sees_the_named_variable_and_not_the_hosts_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TROUPE_TEST_HOST_SECRET", "must-not-leak")
    ran = _run(tmp_path, argv=_fake("echo-env"), env={"TROUPE_TEST_NAMED": "passed"})
    seen = json.loads(next(e for e in ran.events if isinstance(e, p.LogEvent)).message)
    assert seen["TROUPE_TEST_NAMED"] == "passed"
    assert "TROUPE_TEST_HOST_SECRET" not in seen


def test_the_caller_receives_each_event_as_it_arrives(tmp_path: Path) -> None:
    ran = _run(tmp_path, {"steps": [{"event": INIT}, {"wait": {"ms": 700}}, {"event": OK}]})
    assert ran.times[1] - ran.times[0] >= 0.5


# Every message the host sends validates (checked in _run for every test above)


def test_every_message_the_host_sends_in_a_full_run_validates(tmp_path: Path) -> None:
    ran = _run(tmp_path, {"steps": [{"event": INIT}, {"event": OK}]}, cancel_after=None)
    assert len(ran.sent) == 3
    for message in ran.received:
        validate(message, "message.schema.json#/$defs/fromRunner")


# Requirement: Run start carries everything the runner may use (spec: runner-protocol)


def _run_start(ran: Ran) -> dict[str, Any]:
    [start] = [m for m in ran.sent if m.get("method") == "run/start"]
    params: dict[str, Any] = start["params"]
    return params


def test_run_start_carries_the_direction_and_the_character_each_in_its_own_field(
    tmp_path: Path,
) -> None:
    ran = _run(
        tmp_path,
        {"steps": [{"event": INIT}, {"event": OK}]},
        character="You test.",
        direction="test the hello file",
    )
    params = _run_start(ran)
    assert params["direction"] == "test the hello file"
    assert params["character"] == "You test."


def test_an_actor_with_no_character_sends_none_rather_than_a_null(tmp_path: Path) -> None:
    ran = _run(tmp_path, {"steps": [{"event": INIT}, {"event": OK}]})
    assert "character" not in _run_start(ran)


# Requirement: The runner takes direction, character and configuration only from its run start
# (spec: runner-protocol)


def test_neither_the_runners_argv_nor_its_environment_holds_the_direction_character_or_options(
    tmp_path: Path,
) -> None:
    markers = {name: f"troupe-marker-{name}-{uuid.uuid4().hex}" for name in ("d", "c", "o")}
    ran = _run(
        tmp_path,
        {"steps": [{"stderr": markers["o"]}]},
        argv=_fake("echo-argv-and-env"),
        direction=markers["d"],
        character=markers["c"],
    )
    assert ran.outcome.error is None
    params = _run_start(ran)
    assert (params["direction"], params["character"]) == (markers["d"], markers["c"])
    assert markers["o"] in json.dumps(params["options"])
    seen = json.loads(next(e for e in ran.events if isinstance(e, p.LogEvent)).message)
    held = [*seen["argv"], *seen["env"], *seen["env"].values()]
    assert [m for m in markers.values() if any(m in value for value in held)] == []


# Requirement: Every run gets scratch space outside its declaration (spec: effects;
# declared-effects design D6)


def _scratch_seen(ran: Ran) -> dict[str, Any]:
    log = next(e for e in ran.events if isinstance(e, p.LogEvent))
    seen: dict[str, Any] = json.loads(log.message)
    return seen


@pytest.mark.parametrize("status", ["ok", "error"])
def test_a_run_gets_an_empty_scratch_directory_outside_its_workspace_removed_when_it_ends(
    tmp_path: Path, status: str
) -> None:
    workspace, root = tmp_path / "workspace", tmp_path / "scratch-root"
    workspace.mkdir()
    root.mkdir()
    ran = _run(workspace, argv=_fake("inspect-scratch"), direction=status, scratch_root=root)
    seen = _scratch_seen(ran)
    scratch = Path(seen["scratch"])
    assert (seen["exists"], seen["empty"]) == (True, True)
    assert scratch.parent == root.resolve()
    assert scratch.name.startswith(defaults.RUN_SCRATCH_PREFIX)
    assert not scratch.resolve().is_relative_to(workspace.resolve())
    assert _run_start(ran)["scratch"] == seen["scratch"]
    assert ran.outcome.outcome is (Outcome.SUCCEEDED if status == "ok" else Outcome.FAILED)
    assert not scratch.exists()  # gone, with the file the run left in it
    assert ran.notices == []


def test_a_scratch_directory_that_cant_be_removed_is_a_notice_not_a_failed_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(path: object, *args: object, **kwargs: object) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(shutil, "rmtree", refuse)
    workspace, root = tmp_path / "workspace", tmp_path / "scratch-root"
    workspace.mkdir()
    root.mkdir()
    ran = _run(workspace, argv=_fake("inspect-scratch"), direction="ok", scratch_root=root)
    assert ran.outcome.outcome is Outcome.SUCCEEDED
    [notice] = ran.notices
    scratch = _scratch_seen(ran)["scratch"]
    assert notice.code == "run.scratch-not-removed"
    assert notice.details == {"scratch": scratch}
    assert scratch in notice.fix


def test_the_actors_effects_reach_the_runner_with_all_three_lists(tmp_path: Path) -> None:
    effects = p.EffectsDeclaration(write=["out/**"], delete=[], move=["drafts/**"])
    ran = _run(tmp_path, {"steps": [{"event": INIT}, {"event": OK}]}, effects=effects)
    assert _run_start(ran)["effects"] == {"write": ["out/**"], "delete": [], "move": ["drafts/**"]}


def test_a_read_only_actors_run_start_carries_three_empty_lists(tmp_path: Path) -> None:
    ran = _run(tmp_path, {"steps": [{"event": INIT}, {"event": OK}]})
    assert _run_start(ran)["effects"] == {"write": [], "delete": [], "move": []}


def _outside(ran: Ran) -> tuple[Change, ...] | None:
    assert ran.outcome.audit is not None, "the runner started, so the run has an audit"
    return ran.outcome.audit.outside


WRITE_STRAY = {"writeFile": {"path": "src/a.py", "content": "stray\n"}}
STRAY = (Change("src/a.py", "added", "write"),)


def test_an_error_result_keeps_its_error_and_its_audit_names_the_change(tmp_path: Path) -> None:
    ran = _run(
        tmp_path,
        {"steps": [{"event": INIT}, WRITE_STRAY, {"event": ERROR_RESULT}]},
        audit=_audit(tmp_path, Effects(write=("out/**",))),
    )
    assert (ran.outcome.outcome, _code(ran)) == (Outcome.FAILED, "run.error-result")
    assert _outside(ran) == STRAY
    assert ran.outcome.to_data()["audit"] == {
        "outside": [{"path": "src/a.py", "change": "added", "needs": "write"}]
    }


def test_a_timed_out_run_keeps_its_error_and_its_audit_names_the_change(tmp_path: Path) -> None:
    ran = _run(
        tmp_path,
        {"steps": [{"event": INIT}, WRITE_STRAY, {"hang": True}]},
        audit=_audit(tmp_path),
        limits=RunLimits(run_timeout=0.5, cancel_grace=2.0),
    )
    assert (ran.outcome.outcome, _code(ran)) == (Outcome.TIMED_OUT, "run.timeout")
    assert _outside(ran) == STRAY


def test_a_cancelled_run_keeps_no_error_and_its_audit_names_the_change(tmp_path: Path) -> None:
    ran = _run(
        tmp_path,
        {"steps": [{"event": INIT}, WRITE_STRAY, {"hang": True}]},
        audit=_audit(tmp_path),
        cancel_after=0.5,
    )
    assert (ran.outcome.outcome, ran.outcome.error) == (Outcome.CANCELLED, None)
    assert _outside(ran) == STRAY


def test_a_crashed_run_keeps_its_error_and_its_audit_names_the_change(tmp_path: Path) -> None:
    ran = _run(
        tmp_path,
        {"steps": [{"event": INIT}, WRITE_STRAY, {"exit": 3}]},
        audit=_audit(tmp_path),
    )
    assert (ran.outcome.outcome, _code(ran)) == (Outcome.CRASHED, "runner.crashed")
    assert _outside(ran) == STRAY


def test_a_failed_run_that_stayed_inside_its_declaration_has_an_empty_audit(
    tmp_path: Path,
) -> None:
    ran = _run(
        tmp_path,
        {"steps": [{"event": INIT}, WRITE_STRAY, {"event": ERROR_RESULT}]},
        audit=_audit(tmp_path, Effects(write=("src/**",))),
    )
    assert (ran.outcome.outcome, _code(ran)) == (Outcome.FAILED, "run.error-result")
    assert _outside(ran) == ()


def test_a_runner_that_never_answers_the_handshake_is_audited(tmp_path: Path) -> None:
    ran = _run(
        tmp_path,
        argv=_fake("write-then-silent"),
        audit=_audit(tmp_path),
        limits=RunLimits(start_timeout=1.0, cancel_grace=2.0),
    )
    assert (ran.outcome.outcome, _code(ran)) == (Outcome.COULD_NOT_START, "runner.start-timeout")
    assert _outside(ran) == (Change("stray.txt", "added", "write"),)


def test_an_ok_result_with_a_change_outside_fails_with_the_same_findings(tmp_path: Path) -> None:
    ran = _run(
        tmp_path,
        {"steps": [{"event": INIT}, WRITE_STRAY, {"event": OK}]},
        audit=_audit(tmp_path, Effects(write=("out/**",))),
    )
    assert (ran.outcome.outcome, _code(ran)) == (Outcome.FAILED, "effects.outside-declared")
    assert ran.outcome.error is not None
    assert ran.outcome.error.details["changes"] == [c.to_data() for c in _outside(ran) or ()]
    assert _outside(ran) == STRAY


def test_an_ok_result_whose_audit_finds_every_change_declared_succeeds(tmp_path: Path) -> None:
    ran = _run(
        tmp_path,
        {"steps": [{"event": INIT}, WRITE_STRAY, {"event": OK}]},
        audit=_audit(tmp_path, Effects(write=("src/**",))),
    )
    assert (ran.outcome.outcome, ran.outcome.error) == (Outcome.SUCCEEDED, None)
    assert ran.outcome.to_data()["audit"] == {"outside": []}


def _unreadable(tmp_path: Path) -> DeclaredEffects:
    """The audit, over a workspace that can't be read once the run has ended."""

    def unreadable() -> dict[str, str]:
        raise TroupeError(
            "vcs.failed",
            problem="git ls-files failed.",
            fix="Check the repository with git status.",
            details={"command": "git ls-files", "exitStatus": 128},
        )

    return DeclaredEffects("tester", Effects(), lambda: _states(tmp_path), unreadable)


def test_an_ok_result_whose_workspace_cant_be_read_fails_with_audit_failed(
    tmp_path: Path,
) -> None:
    ran = _run(tmp_path, {"steps": [{"event": INIT}, {"event": OK}]}, audit=_unreadable(tmp_path))
    assert (ran.outcome.outcome, _code(ran)) == (Outcome.FAILED, "effects.audit-failed")
    assert ran.outcome.audit is not None
    assert ran.outcome.audit.error is not None
    assert ran.outcome.audit.error.code == "vcs.failed"


def test_a_cancelled_run_whose_workspace_cant_be_read_stays_cancelled(tmp_path: Path) -> None:
    ran = _run(
        tmp_path,
        {"steps": [{"event": INIT}, {"hang": True}]},
        audit=_unreadable(tmp_path),
        cancel_after=0.5,
    )
    assert (ran.outcome.outcome, ran.outcome.error) == (Outcome.CANCELLED, None)
    assert ran.outcome.audit is not None
    assert ran.outcome.audit.error is not None


def test_an_error_result_with_its_expected_file_missing_fails_with_its_error_alone(
    tmp_path: Path,
) -> None:
    ran = _run(
        tmp_path,
        {"steps": [{"event": INIT}, {"event": ERROR_RESULT}]},
        effect=ExpectedFiles([tmp_path / "out" / "hello.txt"]),
        audit=_audit(tmp_path),
    )
    assert (ran.outcome.outcome, _code(ran)) == (Outcome.FAILED, "run.error-result")
    assert ran.outcome.error is not None
    assert "hello.txt" not in ran.outcome.error.problem


# Requirement: The transcript-kinds capability (spec: runner-protocol)

KINDS = [sys.executable, "-m", "troupe_runner_scripted", "--transcript-kinds"]
"""The scripted runner, accepting transcript-kinds when troupe offers it."""


def test_troupe_offers_transcript_kinds_and_a_runner_that_accepts_it_uses_kinds(
    tmp_path: Path,
) -> None:
    ran = _run(tmp_path, {"steps": [{"event": INIT}, {"event": OK}]}, argv=KINDS)
    assert ran.sent[0]["params"]["capabilities"] == ["transcript-kinds"]
    assert ran.received[0]["result"]["capabilities"] == ["transcript-kinds"]
    assert ran.outcome.transcript_format is TranscriptFormat.KINDS


def test_a_runner_that_doesnt_accept_transcript_kinds_has_its_records_stored_unframed(
    tmp_path: Path,
) -> None:
    ran = _run(tmp_path, {"steps": [{"event": INIT}, {"transcript": '{"a":1}'}, {"event": OK}]})
    assert ran.received[0]["result"]["capabilities"] == []
    assert ran.outcome.transcript_format is TranscriptFormat.NATIVE
    assert ran.transcript() == b'{"a":1}\n'


# Requirement: Kinds are all or nothing in a run (spec: runner-protocol)


@pytest.mark.parametrize(
    ("argv", "record", "expected"),
    [
        (KINDS, {"record": "bare"}, "without a kind, after accepting transcript-kinds"),
        (None, {"record": "x", "kind": "received"}, "of kind 'received' without accepting"),
    ],
    ids=["no kind in a run with kinds", "a kind in a run without them"],
)
def test_a_record_that_breaks_the_kinds_rule_is_a_violation_and_isnt_stored(
    tmp_path: Path, argv: list[str] | None, record: dict[str, str], expected: str
) -> None:
    first = {"record": "kept", "kind": "sent"} if argv else {"record": "kept"}
    steps = [{"event": INIT}, {"transcript": first}, {"transcript": record}, {"hang": True}]
    ran = _run(tmp_path, {"onCancel": "ignore", "steps": steps}, argv=argv)
    assert (ran.outcome.outcome, _code(ran)) == (Outcome.CRASHED, "runner.protocol")
    assert ran.outcome.error is not None
    assert expected in ran.outcome.error.problem
    kept = b'{"kind":"sent","record":"kept"}\n' if argv else b"kept\n"
    assert ran.transcript() == kept


# Requirement: A run that uses kinds stores each record with its kind (spec: actor-runners)


def test_a_run_with_kinds_stores_each_record_as_a_line_with_its_kind(tmp_path: Path) -> None:
    steps = [
        {"event": INIT},
        {"transcript": {"record": '{"model":"m"}', "kind": "sent"}},
        {"transcript": {"record": "data: {}", "kind": "received"}},
        {"event": OK},
    ]
    ran = _run(tmp_path, {"steps": steps}, argv=KINDS)
    assert ran.transcript() == (
        b'{"kind":"sent","record":"{\\"model\\":\\"m\\"}"}\n'
        b'{"kind":"received","record":"data: {}"}\n'
    )
    for line in ran.transcript().splitlines():
        validator_for(STORED_RECORD).validate(json.loads(line))


def test_a_base64_record_in_a_run_with_kinds_is_stored_as_base64_of_its_masked_bytes(
    tmp_path: Path,
) -> None:
    raw = b"\x00\xffsk-test-canary-0123456789\xfe"
    record = {"record": base64.b64encode(raw).decode(), "encoding": "base64", "kind": "received"}
    steps = [{"event": INIT}, {"transcript": record}, {"event": OK}]
    ran = _run(tmp_path, {"steps": steps}, argv=KINDS, credential="sk-test-canary-0123456789")
    line = json.loads(ran.transcript())
    assert (line["kind"], line["encoding"]) == ("received", "base64")
    assert base64.b64decode(line["record"]) == b"\x00\xff[credential]\xfe"


def test_the_credential_in_a_record_with_kinds_is_masked_and_the_line_stays_json(
    tmp_path: Path,
) -> None:
    canary = 'sk-"test/canary'
    record = {"record": json.dumps({"key": canary}), "kind": "sent"}
    steps = [{"event": INIT}, {"transcript": record}, {"event": OK}]
    ran = _run(tmp_path, {"steps": steps}, argv=KINDS, credential=canary)
    line = json.loads(ran.transcript())
    assert line == {"kind": "sent", "record": '{"key": "[credential]"}'}
    assert canary.encode() not in ran.transcript()


# A record that is JSON stays JSON once masked (transcript-masking, #438)

JSON_ESCAPE_CANARY = "nsecret-token-0123456789"


def test_a_native_json_line_with_an_escape_before_the_credential_is_stored_valid(
    tmp_path: Path,
) -> None:
    line = '{"type":"assistant","text":"key:\\nsecret-token-0123456789","n":1.50}'
    steps = [{"event": INIT}, {"transcript": line}, {"event": OK}]
    ran = _run(tmp_path, {"steps": steps}, credential=JSON_ESCAPE_CANARY)
    assert ran.outcome.outcome is Outcome.SUCCEEDED, ran.outcome.error
    assert ran.transcript() == b'{"type":"assistant","text":"key:[credential]","n":1.50}\n'
    json.loads(ran.transcript())


@pytest.mark.parametrize(
    ("record", "stored"),
    [
        ('{"input":"\\nsecret-token-0123456789"}', '{"input":"[credential]"}'),
        ('data: {"delta":"\\nsecret-token-0123456789"}', 'data: {"delta":"[credential]"}'),
    ],
    ids=["engine JSON", "data line"],
)
def test_a_kinds_record_that_is_json_is_stored_valid_inside_a_valid_line(
    tmp_path: Path, record: str, stored: str
) -> None:
    steps = [{"event": INIT}, {"transcript": {"record": record, "kind": "sent"}}, {"event": OK}]
    ran = _run(tmp_path, {"steps": steps}, argv=KINDS, credential=JSON_ESCAPE_CANARY)
    assert ran.outcome.outcome is Outcome.SUCCEEDED, ran.outcome.error
    line = json.loads(ran.transcript())
    validator_for(STORED_RECORD).validate(line)
    assert line == {"kind": "sent", "record": stored}
    assert not _holds_a_form(ran.transcript(), JSON_ESCAPE_CANARY)


def test_a_base64_record_that_is_json_is_stored_as_base64_of_valid_json(tmp_path: Path) -> None:
    raw = b'{"t":"\\nsecret-token-0123456789"}'
    record = {"record": base64.b64encode(raw).decode(), "encoding": "base64", "kind": "received"}
    steps = [{"event": INIT}, {"transcript": record}, {"event": OK}]
    ran = _run(tmp_path, {"steps": steps}, argv=KINDS, credential=JSON_ESCAPE_CANARY)
    line = json.loads(ran.transcript())
    assert base64.b64decode(line["record"]) == b'{"t":"[credential]"}'


# Requirement: The transcript limit counts what is stored (spec: actor-runners)


def test_framing_that_passes_the_transcript_limit_stops_the_run(tmp_path: Path) -> None:
    # Ten records of 40 bytes are 410 stored bytes natively, under the limit of 500, and about
    # 700 framed: the framing alone passes the limit.
    record = {"record": "x" * 40, "kind": "received"}
    steps = [{"event": INIT}] + [{"transcript": record}] * 10 + [{"hang": True}]
    # A short run timeout, so counting the wrong bytes fails quickly rather than at the default.
    limits = RunLimits(transcript_max_bytes=500, run_timeout=20.0, cancel_grace=2.0)
    native_steps = [{"event": INIT}] + [{"transcript": "x" * 40}] * 10 + [{"event": OK}]
    native = _run(tmp_path, {"steps": native_steps}, limits=limits)
    assert native.outcome.outcome is Outcome.SUCCEEDED
    assert len(native.transcript()) < 500
    ran = _run(tmp_path, {"steps": steps}, argv=KINDS, limits=limits)
    assert (ran.outcome.outcome, _code(ran)) == (Outcome.FAILED, "run.transcript-too-large")


def test_a_record_whose_framing_would_complete_the_credential_is_stored_masked_as_text(
    tmp_path: Path,
) -> None:
    # JSON writes a newline as \n, so a newline before the rest of a credential that starts with
    # n would put the whole credential in the stored line. The runner writes the newline as
    # \u000a, so its line never holds the credential; troupe masks the newline with the rest
    # (host-robustness design D2), where #315 stored it as base64 of bytes that still decode to
    # most of the credential.
    canary = "nsecret-token-0123456789"
    ran = _run(tmp_path, argv=_fake("escaped-newline-credential"), credential=canary)
    assert ran.outcome.outcome is Outcome.SUCCEEDED, ran.outcome.error
    assert not _holds_a_form(ran.transcript(), canary)
    assert canary[1:].encode() not in ran.transcript()
    line = json.loads(ran.transcript())
    validator_for(STORED_RECORD).validate(line)
    assert line == {"kind": "received", "record": "[credential]"}


# Requirement: troupe masks the credential in everything it keeps from a run
# (host-robustness design D1, D2)

ESCAPE_CANARY = "nsecret-token-0123456789"
"""A credential that starts with n, the letter JSON's escape for a newline ends with (#330)."""


def _raw(
    tmp_path: Path,
    *lines: str,
    next_seq: int = 1,
    kinds: bool = False,
    credential: str | None = ESCAPE_CANARY,
    limits: RunLimits = FAST,
) -> Ran:
    """A run whose runner writes ``lines`` as they are after init, then an ok result."""
    env = {"FAKE_RAW_LINES": json.dumps(list(lines)), "FAKE_RAW_NEXT_SEQ": str(next_seq)}
    if kinds:
        env["FAKE_RAW_KINDS"] = "1"
    return _run(tmp_path, argv=_fake("raw-lines"), env=env, credential=credential, limits=limits)


def _kept(ran: Ran) -> bytes:
    """Every byte the run kept or passed on: its transcript, standard error, the events passed on,
    each oversized event's stored line, its error and its notices."""
    kept = [ran.transcript(), ran.stderr()]
    for event in ran.events:
        kept.append(json.dumps(event.to_data()).encode())
        if isinstance(event, p.OversizedEvent):
            kept.append(ran.store.read(event.ref))
    if ran.outcome.error is not None:
        kept.append(json.dumps(ran.outcome.error.to_data()).encode())
    kept += [json.dumps(notice.to_data()).encode() for notice in ran.notices]
    kept += [json.dumps(message).encode() for message in ran.received]
    return b"\n".join(kept)


def _holds_a_form(data: bytes, credential: str) -> bool:
    return Masker(credential).bytes(data) != data


TRANSCRIPT_LINE = (
    '{"jsonrpc": "2.0", "method": "run/transcript", "params": {"runId": "{run_id}", %s}}'
)


def test_a_newline_escape_before_the_rest_of_the_credential_is_read_and_masked_not_a_violation(
    tmp_path: Path,
) -> None:
    # #330: the wire line holds "\nsecret-token-...", whose raw bytes hold the credential.
    ran = _raw(tmp_path, TRANSCRIPT_LINE % '"record": "\\nsecret-token-0123456789"')
    assert ran.outcome.outcome is Outcome.SUCCEEDED, ran.outcome.error
    assert ran.transcript() == b"[credential]\n"
    assert not _holds_a_form(_kept(ran), ESCAPE_CANARY)


def test_a_newline_escape_before_the_rest_of_the_credential_in_an_event_is_masked(
    tmp_path: Path,
) -> None:
    log = (
        '{"jsonrpc": "2.0", "method": "run/event", "params": {"runId": "{run_id}", "seq": 1, '
        '"type": "log", "level": "info", "message": "key: \\nsecret-token-0123456789."}}'
    )
    ran = _raw(tmp_path, log, next_seq=2)
    assert ran.outcome.outcome is Outcome.SUCCEEDED, ran.outcome.error
    assert isinstance(ran.events[1], p.LogEvent)
    assert ran.events[1].message == "key: [credential]."
    assert not _holds_a_form(_kept(ran), ESCAPE_CANARY)


def test_a_duplicated_key_holding_the_credential_is_named_masked_in_the_violation(
    tmp_path: Path,
) -> None:
    line = (
        '{"jsonrpc": "2.0", "method": "run/event", "params": {"runId": "{run_id}", "seq": 1, '
        f'"{ESCAPE_CANARY}": 1, "{ESCAPE_CANARY}": 2}}}}'
    )
    ran = _raw(tmp_path, line)
    assert (ran.outcome.outcome, _code(ran)) == (Outcome.CRASHED, "runner.protocol")
    assert ran.outcome.error is not None
    assert "[credential]" in ran.outcome.error.problem
    assert not _holds_a_form(_kept(ran), ESCAPE_CANARY)


def test_an_oversized_event_holding_the_credential_is_stored_masked(tmp_path: Path) -> None:
    log = (
        '{"jsonrpc": "2.0", "method": "run/event", "params": {"runId": "{run_id}", "seq": 1, '
        '"type": "log", "level": "info", "message": "' + "y" * 3000 + ESCAPE_CANARY + '"}}'
    )
    ran = _raw(tmp_path, log, next_seq=2, limits=RunLimits(event_max_bytes=1024, cancel_grace=2.0))
    assert ran.types == ["init", "oversized", "result"]
    oversized = ran.events[1]
    assert isinstance(oversized, p.OversizedEvent)
    stored = json.loads(ran.store.read(oversized.ref))
    assert stored["params"]["message"] == "y" * 3000 + "[credential]"
    assert not _holds_a_form(_kept(ran), ESCAPE_CANARY)


def test_an_oversized_event_with_nothing_masked_is_stored_as_the_line_it_was(
    tmp_path: Path,
) -> None:
    # Spaces after the separators, which troupe's own JSON wouldn't write: byte for byte.
    log = (
        '{"jsonrpc": "2.0", "method": "run/event", "params": {"runId": "{run_id}", "seq": 1, '
        '"type": "log", "level": "info", "message": "' + "y" * 3000 + '"}}'
    )
    ran = _raw(tmp_path, log, next_seq=2, limits=RunLimits(event_max_bytes=1024, cancel_grace=2.0))
    oversized = ran.events[1]
    assert isinstance(oversized, p.OversizedEvent)
    assert ran.store.read(oversized.ref) == log.replace("{run_id}", ran.events[0].run_id).encode()


# Requirement: A message's strings are Unicode text (#311, host-robustness D3)


@pytest.mark.parametrize(
    ("line", "path"),
    [
        (TRANSCRIPT_LINE % '"record": "a\\ud800b"', "params.record"),
        (
            '{"jsonrpc": "2.0", "method": "run/event", "params": {"runId": "{run_id}", "seq": 1, '
            '"type": "log", "level": "info", "message": "x\\udfffy"}}',
            "params.message",
        ),
        (
            '{"jsonrpc": "2.0", "method": "run/event", "params": {"runId": "{run_id}", "seq": 1, '
            '"type": "tool_call", "callId": "c1", "tool": "Write", "inputSummary": "s", '
            '"\\ud800": 1}}',
            "params",
        ),
    ],
    ids=["transcript record", "log message", "key"],
)
def test_a_lone_surrogate_in_a_runners_message_is_a_violation_naming_where(
    tmp_path: Path, line: str, path: str
) -> None:
    ran = _raw(tmp_path, line)
    assert (ran.outcome.outcome, _code(ran)) == (Outcome.CRASHED, "runner.protocol")
    assert ran.outcome.error is not None
    assert "lone surrogate" in ran.outcome.error.problem
    assert path in ran.outcome.error.problem
    assert ran.transcript() == b""


# Review of #437: a message troupe can't read or mask without loss is a violation, never an
# unhandled exception or a quiet merge


def test_a_message_nested_past_pythons_recursion_limit_is_a_violation(tmp_path: Path) -> None:
    deep = "[" * 5000 + "]" * 5000
    line = (
        '{"jsonrpc": "2.0", "method": "run/event", "params": {"runId": "{run_id}", "seq": 1, '
        '"type": "log", "level": "info", "message": "m", "x": ' + deep + "}}"
    )
    ran = _raw(tmp_path, line, limits=RunLimits(max_message_bytes=1 << 20, cancel_grace=2.0))
    assert (ran.outcome.outcome, _code(ran)) == (Outcome.CRASHED, "runner.protocol")
    assert ran.outcome.error is not None
    assert "nested" in ran.outcome.error.problem
