"""The run's logic with a stand-in engine, for what a subprocess can't time reliably (spec:
lm-studio-runner, "Cancel and end of input stop the run at once")."""

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from troupe_plugin_sdk.declaration import Declaration
from troupe_plugin_sdk.events import EventNumbering
from troupe_plugin_sdk.runner import RunEvent, RunStartParams, TranscriptKind
from troupe_plugin_sdk.tools import Tools
from troupe_runner_lm_studio.engine import (
    EngineError,
    Failure,
    Fragment,
    Model,
    Round,
    ToolSpec,
)
from troupe_runner_lm_studio.loop import EngineLike, Run
from troupe_runner_lm_studio.options import Options
from troupe_runner_lm_studio.runtime import Runtime

RUN_ID = "11111111-1111-4111-8111-111111111111"


class StandIn:
    """An engine whose act() asks for one Write call, after ``before_call`` has run."""

    def __init__(self, before_call: Callable[[], None]) -> None:
        self.before_call = before_call
        self.answer: str | None = None

    def open(self) -> None:
        pass

    def models(self) -> list[Model]:
        return []

    def load(
        self, model: str, context_length: int, progress: Callable[[float], None]
    ) -> tuple[Any, int, str | None]:
        return object(), context_length, model

    def act(
        self,
        handle: Any,  # noqa: ANN401
        history: dict[str, Any],
        definitions: Sequence[Any],
        *,
        temperature: float | None,
        fragment: Fragment,
        round_done: Callable[[Round], None],
        round_end: Callable[[int], bool],
        message: Callable[[dict[str, Any]], None],
        invalid: Callable[[str, str | None, object], str],
    ) -> int:
        self.before_call()
        carry_out = definitions[0]
        self.answer = carry_out("Write", {"file_path": "out/a.txt", "content": "a"})
        round_done(Round(0, "eosFound", 10, 1, "m", {}))
        round_end(0)
        return 1

    def close(self) -> None:
        pass

    def reopen(self) -> EngineLike:
        return self


def _run(tmp_path: Path, engine: StandIn, stop: list[bool]) -> tuple[Run, list[RunEvent]]:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    start = RunStartParams.from_data(
        {
            "runId": RUN_ID,
            "direction": "Write it.",
            "workspace": str(workspace),
            "options": {},
            "limits": {"eventMaxBytes": 65536},
            "effects": {"write": ["out/**"], "delete": [], "move": []},
            "scratch": str(scratch),
        }
    )
    sent: list[RunEvent] = []

    def record(kind: TranscriptKind, data: bytes) -> None:
        pass

    run = Run(
        runtime=Runtime("http://127.0.0.1:1234", "127.0.0.1:1234", "m"),
        options=Options(max_turns=3, max_total_tokens=1000),
        tools=Tools.for_declaration(Declaration.from_run_start(start)),
        numbering=EventNumbering(RUN_ID, 65536, next_seq=1),
        engine=engine,
        model=Model("m", "llm", True, {}),
        send=sent.append,
        record=record,
        wait=lambda _: True,
        stopping=lambda: stop[0],
        make_definitions=lambda specs, carry_out: [carry_out],
        sent_tools=lambda definitions: [],
    )
    return run, sent


def test_a_call_the_library_asks_for_after_a_stop_isnt_carried_out(tmp_path: Path) -> None:
    stop = [False]
    engine = StandIn(lambda: stop.__setitem__(0, True))
    run, sent = _run(tmp_path, engine, stop)
    assert run.run(None, "Write it.") is None
    assert not (tmp_path / "ws" / "out" / "a.txt").exists()
    assert not [e for e in sent if e.to_data()["type"] in ("tool_call", "tool_result")]
    assert engine.answer is not None
    assert "stopped" in engine.answer


def test_the_same_call_without_a_stop_is_carried_out(tmp_path: Path) -> None:
    stop = [False]
    engine = StandIn(lambda: None)
    run, sent = _run(tmp_path, engine, stop)
    result = run.run(None, "Write it.")
    assert result is not None
    assert (tmp_path / "ws" / "out" / "a.txt").read_text(encoding="utf-8") == "a"
    assert [e.to_data()["type"] for e in sent if e.to_data()["type"].startswith("tool")] == [
        "tool_call",
        "tool_result",
    ]


def test_the_run_offers_the_library_the_sdks_seven_tools_in_order(tmp_path: Path) -> None:
    seen: list[Sequence[ToolSpec]] = []
    stop = [False]
    engine = StandIn(lambda: None)
    run, _ = _run(tmp_path, engine, stop)
    original = run.make_definitions

    def capture(specs: Sequence[ToolSpec], carry_out: Callable[[str, dict[str, Any]], str]) -> Any:  # noqa: ANN401
        seen.append(specs)
        return original(specs, carry_out)

    run.make_definitions = capture
    run.run(None, "Write it.")
    assert [spec.name for spec in seen[0]] == list(Tools.names())


class CallsAfterPrediction(StandIn):
    """An engine in the library's order: each round's prediction is reported done before its
    Read call is carried out (the call waits in the library's pool), then the round ends. It
    asks for rounds until round_end says stop, or ten have gone."""

    def __init__(self) -> None:
        super().__init__(lambda: None)
        self.stopped_after: int | None = None

    def act(
        self,
        handle: Any,  # noqa: ANN401
        history: dict[str, Any],
        definitions: Sequence[Any],
        *,
        temperature: float | None,
        fragment: Fragment,
        round_done: Callable[[Round], None],
        round_end: Callable[[int], bool],
        message: Callable[[dict[str, Any]], None],
        invalid: Callable[[str, str | None, object], str],
    ) -> int:
        carry_out = definitions[0]
        for index in range(10):
            round_done(Round(index, "toolCalls", 10, 1, "m", {}))
            carry_out("Read", {"file_path": "notes.txt"})
            if round_end(index):
                self.stopped_after = index
                return index + 1
        return 10


def test_a_round_whose_calls_run_after_its_prediction_is_reported_still_counts_toward_the_limit(
    tmp_path: Path,
) -> None:
    engine = CallsAfterPrediction()
    run, _ = _run(tmp_path, engine, [False])
    (tmp_path / "ws" / "notes.txt").write_text("n", encoding="utf-8")
    result = run.run(None, "Read it.")
    assert engine.stopped_after == 2
    assert result is not None
    assert result.to_data()["reason"] == "turn-limit"


class LostAfterACall(StandIn):
    """An engine whose connection fails (lost by default) after a round's Write call is carried
    out, before the round ends."""

    failure: Failure = "lost"

    def act(
        self,
        handle: Any,  # noqa: ANN401
        history: dict[str, Any],
        definitions: Sequence[Any],
        *,
        temperature: float | None,
        fragment: Fragment,
        round_done: Callable[[Round], None],
        round_end: Callable[[int], bool],
        message: Callable[[dict[str, Any]], None],
        invalid: Callable[[str, str | None, object], str],
    ) -> int:
        round_done(Round(0, "toolCalls", 10, 1, "m", {}))
        definitions[0]("Write", {"file_path": "out/a.txt", "content": "a"})
        raise EngineError(self.failure, "The connection failed.")


def test_a_connection_lost_after_a_call_before_its_round_ends_isnt_retried(
    tmp_path: Path,
) -> None:
    run, sent = _run(tmp_path, LostAfterACall(lambda: None), [False])
    result = run.run(None, "Write it.")
    assert not [e for e in sent if e.to_data()["type"] == "retry"]
    assert result is not None
    end = result.to_data()
    assert (end["status"], end["reason"], end["notRetried"]) == ("error", "network", "side-effect")
    assert "run a tool twice" in end["message"]
    assert (tmp_path / "ws" / "out" / "a.txt").read_text(encoding="utf-8") == "a"


def test_a_timeout_after_a_call_says_nothing_of_a_retry(tmp_path: Path) -> None:
    engine = LostAfterACall(lambda: None)
    engine.failure = "timeout"
    run, sent = _run(tmp_path, engine, [False])
    result = run.run(None, "Write it.")
    assert not [e for e in sent if e.to_data()["type"] == "retry"]
    assert result is not None
    end = result.to_data()
    assert (end["status"], end["reason"]) == ("error", "network")
    assert "notRetried" not in end
    assert "run a tool twice" not in end["message"]
