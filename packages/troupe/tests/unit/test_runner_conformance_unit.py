"""The conformance checks against runners that keep the contract and runners that break it, in this
process: ``processes.start`` gives a stand-in child whose output a scripted runner writes as it
reads each request, and ``run_actor`` a stand-in outcome (spec: actor-runners; design D13). Nothing
is started and no signal is sent: the stand-in child's kill only records that it was asked.

The checks against real runners, started as processes, are in
integration/test_runner_conformance_integration.py."""

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import pytest

from troupe.core.artifacts import MemoryArtifactStore
from troupe.core.errors import TroupeError
from troupe.core.runners import conformance
from troupe.core.runners.conformance import UNKNOWN_OPTION, CheckResult, check_runner
from troupe.core.runners.effects import NoAudit, NoEffectExpected
from troupe.core.runners.host import OFFERED_CAPABILITIES, RunnerCommand, RunRequest
from troupe.core.runners.limits import RunLimits
from troupe.core.runners.outcome import Ending, Outcome, RunOutcome
from troupe.platform import processes
from troupe_plugin_sdk import runner as p

NAMES = [
    "handshake",
    "version refusal",
    "second initialize refused",
    "second run/start refused",
    "unknown option refused",
    "run/start with a character accepted",
    "cancel acknowledged, then exit",
    "exit on end of input",
    "a whole run: init first, seq, result, shutdown",
]
OPTIONS = {"prompt": "say hi"}
LIMITS = RunLimits(start_timeout=5.0, cancel_grace=0.2, run_timeout=30.0)
SECRET = "sk-conformance-secret"  # noqa: S105 - a stand-in value, checked for where it is masked
CRASHED = {"ending": "exited", "exitCode": 1}
RUNTIME = p.RunStartRuntime.from_data(
    {"name": "local", "endpoint": "http://127.0.0.1:1/v1", "model": "small", "credential": True}
)


@dataclass(frozen=True)
class Runner:
    """How the scripted runner behaves: by default, as the contract says."""

    version: int | None = None
    """The version it chooses, when not the one offered."""
    capabilities: tuple[str, ...] = ()
    initialize_result: Mapping[str, object] | None = None
    refuse_initialize: str | None = None
    """Refuse every initialize with this problem."""
    accept_any_version: bool = False
    refuse_after_refusal: bool = False
    answer_second_initialize: bool = False
    second_initialize_code: str = p.ALREADY_INITIALIZED
    refuse_start: str | None = None
    refuse_start_after_second_initialize: bool = False
    accept_second_start: bool = False
    accept_unknown_option: bool = False
    refuse_character: bool = False
    refuse_cancel: bool = False
    stay_after_cancel: bool = False
    stay_after_input_closes: bool = False
    notify_first: bool = False
    wrong_id: bool = False
    malformed: bool = False
    end_output: bool = False
    silent: bool = False
    start_error: OSError | None = None


def _refusal(id_: object, code: str, problem: str) -> dict[str, object]:
    data = {"code": code, "problem": problem, "fix": "Do it differently."}
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32000, "message": "no", "data": data}}


class _Input:
    """The child's standard input: each line written is a request the runner answers."""

    def __init__(self, child: "Child") -> None:
        self.child = child

    def write(self, line: bytes) -> None:
        assert line.endswith(b"\n")
        self.child.handle(json.loads(line))

    async def drain(self) -> None:
        return None


class Child:
    """A started runner, in this process."""

    def __init__(self, runner: Runner, line_limit: int) -> None:
        self.runner = runner
        self.stdout = asyncio.StreamReader(limit=line_limit)
        self.stdin = _Input(self)
        self.exited = asyncio.Event()
        self.calls: list[str] = []
        self.requests: list[dict[str, Any]] = []
        self.initialized = False
        self.started = False

    def say(self, message: object) -> None:
        self.stdout.feed_data(json.dumps(message).encode() + b"\n")

    def exit(self) -> None:
        if not self.exited.is_set():
            self.stdout.feed_eof()
            self.exited.set()

    def answer(self, id_: int, result: p.Message | Mapping[str, object]) -> None:
        if self.runner.notify_first:
            self.say(p.notification("run/event", p.Empty()))
        if self.runner.malformed:
            self.stdout.feed_data(b"{not json\n")
            return
        data = result.to_data() if isinstance(result, p.Message) else dict(result)
        self.say({"jsonrpc": "2.0", "id": id_ + 1 if self.runner.wrong_id else id_, "result": data})

    def handle(self, message: dict[str, Any]) -> None:
        self.requests.append(message)
        if self.runner.silent:
            return
        if self.runner.end_output:
            self.exit()
            return
        id_, method, params = message["id"], message["method"], message["params"]
        if method == "initialize":
            self.initialize(id_, p.InitializeParams.from_data(params))
        elif method == "run/start":
            self.start(id_, p.RunStartParams.from_data(params))
        elif method == "run/cancel":
            if self.runner.refuse_cancel:
                self.say(_refusal(id_, "runner.protocol", "cancel what?"))
                return
            self.answer(id_, p.Empty())
            if not self.runner.stay_after_cancel:
                self.exit()

    def initialize(self, id_: int, params: p.InitializeParams) -> None:
        r = self.runner
        if r.refuse_initialize is not None:
            self.say(_refusal(id_, "runner.incompatible", r.refuse_initialize))
        elif self.initialized and not r.answer_second_initialize:
            self.say(_refusal(id_, r.second_initialize_code, "already initialized"))
        elif p.PROTOCOL_VERSION not in params.protocol_versions and not r.accept_any_version:
            self.say(_refusal(id_, "runner.incompatible", "no version I speak"))
            self.runner = (
                replace(r, refuse_initialize="refused before") if r.refuse_after_refusal else r
            )
        else:
            self.initialized = True
            result: Mapping[str, object] = r.initialize_result or {
                "protocolVersion": p.PROTOCOL_VERSION if r.version is None else r.version,
                "runner": {"name": "scripted-stand-in", "version": "1.0"},
                "capabilities": list(r.capabilities),
            }
            self.answer(id_, result)

    def start(self, id_: int, params: p.RunStartParams) -> None:
        r = self.runner
        problem = r.refuse_start
        if self.started and not r.accept_second_start:
            problem = "a run is already started"
        elif UNKNOWN_OPTION in params.options and not r.accept_unknown_option:
            problem = f"unknown option {UNKNOWN_OPTION}"
        elif params.character is not None and r.refuse_character:
            problem = "unknown field character"
        elif r.refuse_start_after_second_initialize and len(self.initializes()) > 1:
            problem = "confused by the second initialize"
        if problem is not None:
            self.say(_refusal(id_, "runner.protocol", problem))
            return
        self.started = True
        assert Path(params.scratch).is_dir()
        self.answer(id_, p.RunStartResult(params.run_id))

    def initializes(self) -> list[dict[str, Any]]:
        return [m["params"] for m in self.requests if m["method"] == "initialize"]

    def starts(self) -> list[dict[str, Any]]:
        return [m["params"] for m in self.requests if m["method"] == "run/start"]

    async def wait(self) -> int:
        await self.exited.wait()
        return 0

    def close_stdin(self) -> None:
        self.calls.append("close_stdin")
        if not self.runner.stay_after_input_closes:
            self.say(p.notification("run/event", p.Empty()))
            self.exit()

    def kill_tree(self) -> None:
        self.calls.append("kill_tree")
        self.exit()

    def release(self) -> None:
        self.calls.append("release")


@dataclass
class Stage:
    """What the checks started and ran: each child, how it was started, and the whole run."""

    runner: Runner
    children: list[Child] = field(default_factory=list)
    started: list[dict[str, Any]] = field(default_factory=list)
    whole: list[tuple[RunnerCommand, RunRequest, dict[str, Any]]] = field(default_factory=list)
    outcome: Outcome = Outcome.SUCCEEDED
    error: TroupeError | None = None

    async def start(self, argv: list[str], **options: Any) -> Child:  # noqa: ANN401
        self.started.append({"argv": argv, **options})
        if self.runner.start_error is not None:
            raise self.runner.start_error
        child = Child(self.runner, options["line_limit"])
        self.children.append(child)
        return child

    async def run_actor(
        self,
        command: RunnerCommand,
        request: RunRequest,
        **options: Any,  # noqa: ANN401
    ) -> RunOutcome:
        self.whole.append((command, request, options))
        return RunOutcome(
            run_id=request.run_id,
            outcome=self.outcome,
            error=self.error,
            result=None,
            exit_code=0,
            ending=Ending.EXITED,
            transcript=None,
            transcript_format=None,
            stderr=None,
            limits=options["limits"],
        )


@pytest.fixture
def stage(monkeypatch: pytest.MonkeyPatch) -> Stage:
    made = Stage(Runner())
    monkeypatch.setattr(processes, "start", made.start)
    monkeypatch.setattr(conformance, "run_actor", made.run_actor)
    return made


COMMAND = RunnerCommand(
    argv=["runner", "--serve"], cwd=Path("/nowhere"), env={"RUNNER_X": "1"}, search_path="/bin"
)


def _check(
    stage: Stage,
    runner: Runner | None = None,
    *,
    limits: RunLimits | None = LIMITS,
    credential: str | None = None,
    runtime: p.RunStartRuntime | None = None,
    workspace: Path = Path("/workspace"),
) -> list[CheckResult]:
    if runner is not None:
        stage.runner = runner
    return asyncio.run(
        check_runner(
            COMMAND,
            OPTIONS,
            workspace=workspace,
            limits=limits,
            runtime=runtime,
            credential=credential,
        )
    )


def _problems(results: list[CheckResult]) -> dict[str, str | None]:
    assert all(r.passed is True or r.passed is False for r in results)
    return {r.name: r.problem for r in results if not r.passed}


# A runner that keeps the contract


def test_a_runner_that_keeps_the_contract_passes_every_check(stage: Stage) -> None:
    results = _check(stage)
    assert results == [CheckResult(name, True) for name in NAMES]


def test_each_check_starts_the_runner_afresh_and_kills_it_after(stage: Stage) -> None:
    _check(stage)
    assert len(stage.children) == 8
    for child in stage.children:
        assert child.calls[-2:] == ["kill_tree", "release"]
    assert stage.children[7].calls == ["close_stdin", "kill_tree", "release"]
    for started in stage.started:
        assert started["argv"] == ["runner", "--serve"]
        assert started["cwd"] == Path("/nowhere")
        assert started["env"]["RUNNER_X"] == "1"
        assert started["line_limit"] == LIMITS.max_message_bytes
        assert started["search_path"] == "/bin"


def test_what_each_check_offers_in_initialize(stage: Stage) -> None:
    _check(stage)
    offered = [
        [(i["protocolVersions"], i["capabilities"]) for i in c.initializes()]
        for c in stage.children
    ]
    plain: tuple[list[int], list[str]] = ([p.PROTOCOL_VERSION], [])
    assert offered == [
        [plain],
        [([9999], []), plain],
        [([p.PROTOCOL_VERSION], list(OFFERED_CAPABILITIES)), plain],
        [plain],
        [plain],
        [plain],
        [plain],
        [plain],
    ]
    host = stage.children[0].initializes()[0]["host"]
    assert host["name"] == "troupe-conformance"
    assert host["version"]


def test_what_each_run_start_asks_for(stage: Stage) -> None:
    _check(stage, runtime=RUNTIME)
    starts = [c.starts() for c in stage.children]
    assert [len(s) for s in starts] == [0, 0, 1, 2, 1, 1, 1, 1]
    every = [s for c in starts for s in c]
    for start in every:
        assert start["direction"] == "conformance check"
        assert start["workspace"] == str(Path("/workspace"))
        assert start["limits"] == {"eventMaxBytes": LIMITS.event_max_bytes}
        assert start["effects"] == p.READ_ONLY_DECLARATION.to_data()
        assert start["onContextFull"] == "fail"
        assert start["runtime"] == RUNTIME.to_data()
        assert not Path(start["scratch"]).exists()
    assert len({s["runId"] for s in every}) == len(every)
    assert len({s["scratch"] for s in every}) == len(every)
    assert [s["options"] for s in starts[4]] == [{**OPTIONS, UNKNOWN_OPTION: True}]
    assert all(s["options"] == OPTIONS for i, c in enumerate(starts) if i != 4 for s in c)
    assert [s.get("character") for s in starts[5]] == ["You are a conformance check."]
    assert all(s.get("character") is None for i, c in enumerate(starts) if i != 5 for s in c)


def test_request_ids_count_up_from_one(stage: Stage) -> None:
    _check(stage)
    assert [[m["id"] for m in c.requests] for c in stage.children][:4] == [
        [1],
        [1, 2],
        [1, 2, 3],
        [1, 2, 3],
    ]
    assert all(m["jsonrpc"] == "2.0" for c in stage.children for m in c.requests)


def test_the_whole_run_is_run_as_perform_runs_it(stage: Stage, tmp_path: Path) -> None:
    _check(stage, runtime=RUNTIME, credential=SECRET, workspace=tmp_path)
    ((command, request, options),) = stage.whole
    assert command is COMMAND
    assert request.direction == "conformance check"
    assert request.workspace == tmp_path
    assert request.options == OPTIONS
    assert request.runtime == RUNTIME
    assert request.credential == SECRET
    assert len(request.run_id) == 36
    assert isinstance(options["store"], MemoryArtifactStore)
    assert isinstance(options["effect"], NoEffectExpected)
    assert isinstance(options["audit"], NoAudit)
    assert options["limits"] is LIMITS


def test_with_no_limits_given_a_run_may_take_two_minutes(stage: Stage) -> None:
    _check(stage, limits=None)
    assert stage.whole[0][2]["limits"] == RunLimits(run_timeout=120.0)
    assert stage.started[0]["line_limit"] == RunLimits().max_message_bytes


def test_notifications_before_an_answer_are_skipped(stage: Stage) -> None:
    assert _problems(_check(stage, Runner(notify_first=True))) == {}


# A runner that breaks it, check by check


@pytest.mark.parametrize(
    ("runner", "name", "problem"),
    [
        (
            Runner(version=1),
            "handshake",
            "it chose version 1, which wasn't offered",
        ),
        (
            Runner(capabilities=("transcript-kinds",)),
            "handshake",
            "it named capabilities that weren't offered: ['transcript-kinds']",
        ),
        (
            Runner(initialize_result={"protocolVersion": 0}),
            "handshake",
            None,
        ),
        (
            Runner(accept_any_version=True),
            "version refusal",
            "it accepted protocol version 9999, which no runner supports",
        ),
        (
            Runner(refuse_after_refusal=True),
            "version refusal",
            "it refused initialize offering version 0 after one it refused for its versions "
            "(runner.incompatible): a refused initialize isn't a handshake",
        ),
        (
            Runner(answer_second_initialize=True),
            "second initialize refused",
            "it answered a second initialize, which it refuses with runner.already-initialized",
        ),
        (
            Runner(second_initialize_code="runner.protocol"),
            "second initialize refused",
            "it refused a second initialize with runner.protocol, not runner.already-initialized",
        ),
        (
            Runner(refuse_start_after_second_initialize=True),
            "second initialize refused",
            "it refused run/start after a second initialize: confused by the second initialize",
        ),
        (
            Runner(accept_second_start=True),
            "second run/start refused",
            "it accepted a second run/start in the same process",
        ),
        (
            Runner(accept_unknown_option=True),
            "unknown option refused",
            f"it accepted the option {UNKNOWN_OPTION!r}, which no runner defines, instead of "
            "refusing it",
        ),
        (
            Runner(refuse_character=True),
            "run/start with a character accepted",
            "it refused run/start: unknown field character",
        ),
        (
            Runner(refuse_cancel=True),
            "cancel acknowledged, then exit",
            "it refused run/cancel: cancel what?",
        ),
        (
            Runner(stay_after_cancel=True),
            "cancel acknowledged, then exit",
            "it didn't exit within 0.2s of run/cancel",
        ),
        (
            Runner(stay_after_input_closes=True),
            "exit on end of input",
            "it didn't exit within 0.2s of its input closing",
        ),
    ],
)
def test_each_check_fails_naming_what_the_runner_did(
    stage: Stage, runner: Runner, name: str, problem: str | None
) -> None:
    problems = _problems(_check(stage, runner))
    assert list(problems) == [name]
    if problem is None:
        found = problems[name]
        assert found is not None
        assert found.startswith("its initialize answer breaks the contract: ")
    else:
        assert problems[name] == problem


def test_a_refused_initialize_fails_every_check_that_needs_a_handshake(stage: Stage) -> None:
    problems = _problems(_check(stage, Runner(refuse_initialize="not today")))
    assert problems == {
        "handshake": "it refused initialize: not today",
        "second initialize refused": "it refused initialize: not today",
        "second run/start refused": "it refused initialize: not today",
        "unknown option refused": "it refused initialize: not today",
        "run/start with a character accepted": "it refused initialize: not today",
        "cancel acknowledged, then exit": "it refused initialize: not today",
        "exit on end of input": "it refused initialize: not today",
        "version refusal": "it refused initialize offering version 0 after one it refused for "
        "its versions (runner.incompatible): a refused initialize isn't a handshake",
    }


def test_a_refused_run_start_names_the_step(stage: Stage) -> None:
    problems = _problems(_check(stage, Runner(refuse_start="no workspace")))
    assert problems == {
        "second initialize refused": "it refused run/start after a second initialize: no workspace",
        "second run/start refused": "it refused run/start: no workspace",
        "run/start with a character accepted": "it refused run/start: no workspace",
        "cancel acknowledged, then exit": "it refused run/start: no workspace",
        "exit on end of input": "it refused run/start: no workspace",
    }


# Answers that break the contract, whichever check gets them


def test_an_answer_to_another_request_fails_every_check(stage: Stage) -> None:
    problems = _problems(_check(stage, Runner(wrong_id=True)))
    expected = {name: "it answered id 2 while troupe waited for 1" for name in NAMES[:8]}
    # version refusal's first initialize is refused, which answers the right id: its second isn't
    expected["version refusal"] = "it answered id 3 while troupe waited for 2"
    assert problems == expected


def test_a_line_that_isnt_json_fails_every_check(stage: Stage) -> None:
    problems = _problems(_check(stage, Runner(malformed=True)))
    assert list(problems) == NAMES[:8]
    for problem in problems.values():
        assert problem is not None
        assert problem.startswith("it wrote a line that breaks the contract: ")


def test_output_that_ends_before_an_answer_fails_every_check(stage: Stage) -> None:
    problems = _problems(_check(stage, Runner(end_output=True)))
    assert problems == {
        name: "the runner ended its output before answering request 1" for name in NAMES[:8]
    }


def test_a_runner_that_never_answers_times_out(stage: Stage) -> None:
    limits = replace(LIMITS, start_timeout=0.05)
    problems = _problems(_check(stage, Runner(silent=True), limits=limits))
    assert problems == {name: "it didn't answer within 0.05s" for name in NAMES[:8]}


def test_a_runner_that_cant_start_fails_every_check_with_why(stage: Stage) -> None:
    problems = _problems(_check(stage, Runner(start_error=FileNotFoundError(2, "no runner"))))
    assert problems == {name: "[Errno 2] no runner" for name in NAMES[:8]}
    assert stage.children == []


# The whole run, and the credential


def test_a_whole_run_that_fails_names_how_it_ended(stage: Stage) -> None:
    stage.outcome = Outcome.FAILED
    stage.error = TroupeError(
        "runner.crashed", problem="it crashed", fix="Fix it.", details=CRASHED
    )
    assert _problems(_check(stage)) == {NAMES[8]: "the run ended failed: it crashed"}


def test_a_whole_run_that_ends_without_an_error_names_how(stage: Stage) -> None:
    stage.outcome = Outcome.CANCELLED
    assert _problems(_check(stage)) == {NAMES[8]: "the run ended cancelled"}


def test_the_credential_is_masked_in_every_problem(stage: Stage) -> None:
    stage.outcome = Outcome.FAILED
    stage.error = TroupeError(
        "runner.crashed", problem=f"bad key {SECRET}", fix="Fix it.", details=CRASHED
    )
    problems = _problems(
        _check(stage, Runner(refuse_initialize=f"key {SECRET}"), credential=SECRET)
    )
    assert problems["handshake"] == "it refused initialize: key [credential]"
    assert problems[NAMES[8]] == "the run ended failed: bad key [credential]"
    assert all(SECRET not in (problem or "") for problem in problems.values())


def test_without_a_credential_nothing_is_masked(stage: Stage) -> None:
    problems = _problems(_check(stage, Runner(refuse_initialize=f"key {SECRET}")))
    assert problems["handshake"] == f"it refused initialize: key {SECRET}"


def test_cancel_names_the_run_the_runner_started(stage: Stage) -> None:
    _check(stage)
    cancelling = stage.children[6]
    (start,) = cancelling.starts()
    (cancel,) = [m["params"] for m in cancelling.requests if m["method"] == "run/cancel"]
    assert cancel == {"runId": start["runId"]}
