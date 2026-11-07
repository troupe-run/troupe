"""Tests for the run host, driving real runner processes (spec: actor-runners, runner-protocol)."""

import asyncio
import base64
import dataclasses
import json
import shutil
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from protocol_schemas import check_error, check_notice
from runner_schemas import is_valid, validate
from troupe.core import defaults
from troupe.core.artifacts import ArtifactStore, MemoryArtifactStore, load_store
from troupe.core.errors import TroupeError
from troupe.core.notices import Notice
from troupe.core.runners.effects import (
    Audit,
    Change,
    DeclaredEffects,
    EffectCheck,
    ExpectedFiles,
    NoAudit,
    NoEffectExpected,
)
from troupe.core.runners.host import RunnerCommand, RunRequest, run_actor
from troupe.core.runners.limits import RunLimits
from troupe.core.runners.outcome import Ending, Outcome, RunOutcome
from troupe.platform import processes
from troupe_plugin_sdk import runner as p
from troupe_plugin_sdk.effects import Effects

FAKE = Path(__file__).with_name("fake_runner.py")
INIT = {"type": "init", "runner": {"name": "scripted", "version": "0.0.1"}, "tools": ["Write"]}
OK = {"type": "result", "status": "ok", "message": "done"}
ERROR_RESULT = {"type": "result", "status": "error", "message": "API Error: 401"}
FAST = RunLimits(cancel_grace=2.0, start_timeout=30.0)


@dataclass
class Ran:
    outcome: RunOutcome
    store: ArtifactStore
    events: list[p.RunEvent] = field(default_factory=list)
    notices: list[Notice] = field(default_factory=list)
    sent: list[dict[str, Any]] = field(default_factory=list)
    received: list[dict[str, Any]] = field(default_factory=list)
    times: list[float] = field(default_factory=list)

    @property
    def types(self) -> list[str]:
        return [str(e.TYPE) for e in self.events]

    def transcript(self) -> bytes:
        assert self.outcome.transcript is not None
        return self.store.read(self.outcome.transcript)

    def stderr(self) -> bytes:
        assert self.outcome.stderr is not None
        return self.store.read(self.outcome.stderr)


def _run(
    tmp_path: Path,
    script: dict[str, Any] | None = None,
    *,
    argv: list[str] | None = None,
    effect: EffectCheck | None = None,
    audit: Audit | None = None,
    limits: RunLimits = FAST,
    store: ArtifactStore | None = None,
    env: dict[str, str] | None = None,
    cancel_after: float | None = None,
    options: dict[str, Any] | None = None,
    valid_options: bool = True,
    character: str | None = None,
    direction: str = "test",
    effects: p.EffectsDeclaration = p.READ_ONLY_DECLARATION,
    scratch_root: Path | None = None,
    runtime: p.RunStartRuntime | None = None,
) -> Ran:
    """Run the scripted runner (or ``argv``) and check every message troupe sent against the
    contract, with the scripted runner's schemas bound. ``valid_options=False`` marks options the
    runner must refuse, which its options schema must refuse too."""
    store = store if store is not None else MemoryArtifactStore()
    command = RunnerCommand(
        argv or [sys.executable, "-m", "troupe_runner_scripted"], cwd=tmp_path, env=env or {}
    )
    request = RunRequest(
        str(uuid.uuid4()),
        direction,
        tmp_path,
        options if options is not None else {"script": script or {"steps": []}},
        character=character,
        effects=effects,
        runtime=runtime,
    )
    ran: dict[str, Any] = {"events": [], "notices": [], "sent": [], "received": [], "times": []}

    async def on_event(event: p.RunEvent) -> None:
        ran["events"].append(event)
        ran["times"].append(time.monotonic())

    def on_message(direction: str, message: Any) -> None:  # noqa: ANN401
        ran["sent" if direction == "sent" else "received"].append(dict(message))

    async def main() -> RunOutcome:
        cancel = asyncio.Event()
        if cancel_after is not None:
            asyncio.get_running_loop().call_later(cancel_after, cancel.set)
        return await run_actor(
            command,
            request,
            store=store,
            effect=effect or NoEffectExpected(),
            audit=audit or NoAudit(),
            limits=limits,
            on_event=on_event,
            on_announce=ran["notices"].append,
            on_message=on_message,
            cancel=cancel,
            scratch_root=scratch_root,
        )

    outcome = asyncio.run(main())
    result = Ran(outcome, store, **ran)
    if outcome.error is not None:
        check_error(outcome.error.to_data())
    for notice in result.notices:
        check_notice(notice.to_data())
    for message in result.sent:
        if message.get("method") == "run/start" and not valid_options:
            assert not is_valid(message, "message.schema.json#/$defs/fromHost")
        else:
            validate(message, "message.schema.json#/$defs/fromHost")
    return result


def _fake(mode: str) -> list[str]:
    return [sys.executable, str(FAKE), mode]


def _code(ran: Ran) -> str | None:
    return None if ran.outcome.error is None else ran.outcome.error.code


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


def test_a_runner_command_that_does_not_exist_could_not_start(tmp_path: Path) -> None:
    ran = _run(tmp_path, argv=["troupe-no-such-runner"])
    assert (ran.outcome.outcome, _code(ran)) == (Outcome.COULD_NOT_START, "runner.start-failed")
    assert ran.outcome.error is not None
    assert "troupe-no-such-runner" in ran.outcome.error.problem
    assert ran.outcome.transcript is None
    assert ran.outcome.ending is Ending.NEVER_STARTED


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


# Requirement: Protocol violations end the run


@pytest.mark.parametrize(
    ("steps", "expected"),
    [
        ([{"rawStdout": "not json at all"}, {"hang": True}], "not JSON"),
        ([{"rawStdout": '{"some": "object"}'}, {"hang": True}], "JSON-RPC 2.0"),
        ([{"event": INIT}, {"event": {**OK, "seq": 3}}, {"hang": True}], "should have been 1"),
        ([{"event": INIT}, {"event": {**OK, "seq": 0}}, {"hang": True}], "should have been 1"),
        ([{"event": {**OK, "seq": 0}}, {"hang": True}], "not 'init'"),
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
        "unknown method",
        "tool result without call",
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
UNPRICED = p.RunStartRuntime("lm-studio", "http://127.0.0.1:1234/v1", "m", credential=False)


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


def test_a_late_event_after_the_result_crashes_the_run_whether_the_runner_answers_shutdown_first(
    tmp_path: Path,
) -> None:
    # The host sends shutdown on the result, and the hanging runner answers it by exiting 0. That
    # exit and the host's kill for the late event race, so either can end the runner, and the
    # ending must say which did.
    late = {"event": {"type": "log", "level": "info", "message": "late"}}
    ran = _run(tmp_path, {"steps": [{"event": INIT}, {"event": OK}, late, {"hang": True}]})
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
        ("capability", "capabilities troupe didn't offer (resume)"),
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
    assert ran.sent[0]["params"]["capabilities"] == []
    assert ran.received[0]["result"]["protocolVersion"] == 0


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


# Requirement: The audit's findings are part of the outcome (failed-run-audit design D1)


def _states(root: Path) -> dict[str, str]:
    """Every file under ``root``, as the files adapter reads a workspace: path to content."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes().hex()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _audit(tmp_path: Path, effects: Effects | None = None) -> DeclaredEffects:
    """The real audit, over the run's workspace, as perform builds it for a run in the theatre."""
    return DeclaredEffects(
        "tester", effects or Effects(), lambda: _states(tmp_path), lambda: _states(tmp_path)
    )


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


def test_a_runner_that_couldnt_be_started_has_no_audit(tmp_path: Path) -> None:
    ran = _run(tmp_path, argv=["troupe-no-such-runner"], audit=_audit(tmp_path))
    assert (ran.outcome.outcome, _code(ran)) == (Outcome.COULD_NOT_START, "runner.start-failed")
    assert ran.outcome.audit is None
    assert "audit" not in ran.outcome.to_data()


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
