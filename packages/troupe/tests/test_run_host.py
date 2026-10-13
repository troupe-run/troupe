"""Tests for the run host, driving real runner processes (spec: actor-runners, runner-protocol)."""

import asyncio
import base64
import json
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from protocol_schemas import check_error, check_notice
from runner_schemas import is_valid, validate
from troupe.core.artifacts import ArtifactStore, MemoryArtifactStore, load_store
from troupe.core.notices import Notice
from troupe.core.runners import protocol as p
from troupe.core.runners.effects import EffectCheck, ExpectedFiles, NoEffectExpected
from troupe.core.runners.host import RunnerCommand, RunRequest, run_actor
from troupe.core.runners.limits import RunLimits
from troupe.core.runners.outcome import Ending, Outcome, RunOutcome
from troupe.platform import processes

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
    limits: RunLimits = FAST,
    store: ArtifactStore | None = None,
    env: dict[str, str] | None = None,
    cancel_after: float | None = None,
    options: dict[str, Any] | None = None,
    valid_options: bool = True,
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
        "test",
        tmp_path,
        options if options is not None else {"script": script or {"steps": []}},
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
            limits=limits,
            on_event=on_event,
            on_announce=ran["notices"].append,
            on_message=on_message,
            cancel=cancel,
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
            [
                {"event": INIT},
                {"event": OK},
                {"event": {"type": "log", "level": "info", "message": "late"}},
                {"hang": True},
            ],
            "after its result",
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
        "after result",
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
        ("wrong-version", "protocol version 2"),
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
    assert ran.sent[0]["params"]["protocolVersions"] == [1]
    assert ran.sent[0]["params"]["capabilities"] == []
    assert ran.received[0]["result"]["protocolVersion"] == 1


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
    assert notice.details["reason"] == "rate-limit"


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
