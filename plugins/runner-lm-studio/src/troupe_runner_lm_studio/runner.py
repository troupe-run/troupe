"""The LM Studio runner's process: the runner contract over standard input and output
(lmstudio-runner design D6, D9).

The main thread reads troupe's messages and answers them. Before it answers run/start, it checks
everything that can be refused: the params, the options, the runtime, the workspace, and LM Studio
itself (there, with the run's model downloaded and trained for tool use). After it answers, a
worker thread sends init and runs the library's tool loop to its result.

Every line goes to standard output whole, under one lock. Stopping (on run/cancel, end of input or
shutdown) sets a flag under that same lock before the answer is written, so nothing the worker
sends can follow it. Then the engine is closed, which ends the library's prediction at once.
"""

import contextlib
import json
import logging
import os
import queue
import sys
import threading
import traceback
from importlib.resources import files
from typing import Any, BinaryIO, NoReturn

from troupe_plugin_sdk import runner as p
from troupe_plugin_sdk.declaration import Declaration
from troupe_plugin_sdk.events import EventNumbering, cut
from troupe_plugin_sdk.tools import Tools
from troupe_runner_lm_studio import NAME, __version__
from troupe_runner_lm_studio.defaults import STOP_GRACE_SECONDS, SUMMARY_MAX_BYTES
from troupe_runner_lm_studio.engine import Engine, configure, sent_tools, tool_definitions
from troupe_runner_lm_studio.loop import EngineLike, RefusedError, Run, check
from troupe_runner_lm_studio.options import OptionsError, parse_options
from troupe_runner_lm_studio.runtime import RuntimeRefusedError, from_run_start

ENGINE = "lm-studio"
"""The engine the init event names."""

_TROUPE = "troupe"
_TROUPE_EOF = "troupe-eof"
_WORKER_DONE = "worker-done"


def version_tested_with() -> str:
    """The LM Studio version the runner's published requirements name (design D6)."""
    data = json.loads(files("troupe_runner_lm_studio").joinpath("requirements.json").read_text())
    for requirement in data["requires"]:
        if requirement["name"] == "lm-studio":
            return str(requirement["minimum"])
    raise ValueError("requirements.json names no lm-studio requirement")


class _Exit(Exception):  # noqa: N818 - control flow, not an error
    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [key for key, _ in pairs]
    duplicated = sorted({key for key in keys if keys.count(key) > 1})
    if duplicated:
        raise ValueError(f"duplicate key {duplicated[0]!r}")
    return dict(pairs)


def _no_constant(constant: str) -> Any:  # noqa: ANN401 - json's parse_constant hook
    raise ValueError(f"{constant} isn't JSON")


def loads_strict(text: str) -> Any:  # noqa: ANN401 - JSON
    """JSON as the contract reads it: no duplicate keys, no NaN or Infinity."""
    return json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_no_constant)


class _StderrHandler(logging.Handler):
    """The library's warnings and errors, each one line on standard error, cut to fit (design
    D11). Nothing it logs reaches standard output."""

    def __init__(self, write: Any) -> None:  # noqa: ANN401 - the runner's diagnose
        super().__init__(logging.WARNING)
        self._write = write

    def emit(self, record: logging.LogRecord) -> None:
        with contextlib.suppress(Exception):
            text = f"{record.levelname.lower()} from {record.name}: {record.getMessage()}"
            self._write(cut(text.replace("\n", " "), SUMMARY_MAX_BYTES))


class Runner:
    def __init__(
        self,
        stdin: BinaryIO,
        stdout: BinaryIO,
        stderr: BinaryIO,
        environ: dict[str, str] | None = None,
        make_engine: Any = Engine,  # noqa: ANN401 - Engine, or a stand-in in tests
    ) -> None:
        self._stdin = stdin
        self._stdout = stdout
        self._stderr = stderr
        self._environ = dict(os.environ) if environ is None else environ
        self._make_engine = make_engine
        self._inbox: queue.Queue[tuple[str, bytes]] = queue.Queue()
        self._out = threading.Lock()
        self._stop = threading.Event()
        self._kinds = False
        """Whether troupe offered transcript-kinds, which this runner then accepts."""
        self._initialized = False
        self._run_id: str | None = None
        self._worker: threading.Thread | None = None
        self._engine: EngineLike | None = None
        self._engine_lock = threading.Lock()
        self._failed = False

    # Output

    def _write(self, message: dict[str, Any], *, from_worker: bool = False) -> bool:
        """Write one message as one line. A message from the worker is dropped once the run is
        stopping; False when it was."""
        text = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        line = text.encode("utf-8", "backslashreplace") + b"\n"
        with self._out:
            if from_worker and self._stop.is_set():
                return False
            self._stdout.write(line)
            self._stdout.flush()
            return True

    def _diagnose(self, text: str) -> None:
        self._stderr.write(f"lm-studio runner: {text}\n".encode("utf-8", "backslashreplace"))
        self._stderr.flush()

    def _result(self, id_: object, result: dict[str, Any]) -> None:
        self._write({"jsonrpc": "2.0", "id": id_, "result": result})

    def _error(
        self,
        id_: object,
        rpc_code: int,
        code: str,
        problem: str,
        fix: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        data: dict[str, Any] = {"code": code, "problem": problem, "fix": fix}
        if details is not None:
            data["details"] = details
        self._write(
            {
                "jsonrpc": "2.0",
                "id": id_,
                "error": {"code": rpc_code, "message": problem, "data": data},
            }
        )

    # What the run reports through

    def event(self, event: p.RunEvent) -> None:
        self._write(
            {"jsonrpc": "2.0", "method": "run/event", "params": event.to_data()}, from_worker=True
        )

    def transcript(self, kind: p.TranscriptKind, data: bytes) -> None:
        """Send one transcript record: its kind only when troupe offered transcript-kinds. The
        records are the library's JSON, so always UTF-8 text."""
        params: dict[str, Any] = {"runId": self._run_id, "record": data.decode("utf-8")}
        if self._kinds:
            params["kind"] = kind
        self._write(
            {"jsonrpc": "2.0", "method": "run/transcript", "params": params}, from_worker=True
        )

    def _set_engine(self, engine: EngineLike) -> None:
        with self._engine_lock:
            self._engine = engine
        if self._stop.is_set():
            engine.close()

    # Input

    def _read_troupe(self) -> None:
        for line in iter(self._stdin.readline, b""):
            self._inbox.put((_TROUPE, line))
        self._inbox.put((_TROUPE_EOF, b""))

    def run(self) -> int:
        """Serve troupe until the run ends; the exit code."""
        logging.getLogger().addHandler(_StderrHandler(self._diagnose))
        configure()
        threading.Thread(target=self._read_troupe, daemon=True).start()
        try:
            while True:
                kind, data = self._inbox.get()
                if kind == _TROUPE:
                    self._handle(data)
                elif kind == _TROUPE_EOF:
                    self._diagnose("troupe closed standard input; stopping")
                    self._halt()
                    raise _Exit(1 if self._failed else 0)
                # _WORKER_DONE: the result is out (or the run failed); wait for shutdown.
        except _Exit as done:
            return done.code
        except Exception:
            self._diagnose("the runner failed:\n" + traceback.format_exc())
            self._halt()
            return 1

    def _handle(self, line: bytes) -> None:
        try:
            message = loads_strict(line.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            self._error(
                None,
                p.JSONRPC_PARSE_ERROR,
                "runner.parse-error",
                f"The message isn't JSON: {error}",
                "Send JSON.",
            )
            return
        if (
            not isinstance(message, dict)
            or message.get("jsonrpc") != "2.0"
            or not isinstance(message.get("method"), str)
        ):
            self._error(
                None,
                p.JSONRPC_INVALID_REQUEST,
                "runner.invalid-request",
                "Not a JSON-RPC 2.0 request.",
                "Send a JSON-RPC 2.0 request.",
            )
            return
        id_ = message.get("id")
        method = message["method"]
        params = message.get("params", {})
        if method == "initialize":
            self._initialize(id_, params)
        elif not self._initialized:
            self._error(
                id_,
                p.JSONRPC_INVALID_REQUEST,
                "runner.not-initialized",
                f"{method!r} came before initialize.",
                "Send initialize first.",
            )
        elif method == "run/start":
            self._start(id_, params)
        elif method == "run/cancel":
            self._end(id_, "troupe cancelled the run")
        elif method == "shutdown":
            self._end(id_, None)
        else:
            self._error(
                id_,
                p.JSONRPC_METHOD_NOT_FOUND,
                "runner.unknown-method",
                f"The LM Studio runner doesn't know the method {method!r}.",
                "Use a method of the runner contract.",
            )

    def _initialize(self, id_: object, params: object) -> None:
        offered = params.get("protocolVersions") if isinstance(params, dict) else None
        versions = (
            [v for v in offered if isinstance(v, int) and not isinstance(v, bool)]
            if isinstance(offered, list)
            else []
        )
        if not any(v in p.PROTOCOL_VERSIONS for v in versions):
            self._error(
                id_,
                p.JSONRPC_REFUSED,
                "runner.unsupported-version",
                f"The LM Studio runner supports protocol version(s) "
                f"{list(p.PROTOCOL_VERSIONS)}, none of which was offered ({offered!r}).",
                "Offer a protocol version this runner supports.",
                {"supportedVersions": list(p.PROTOCOL_VERSIONS)},
            )
            return
        self._initialized = True
        chosen = max(v for v in versions if v in p.PROTOCOL_VERSIONS)
        offered_capabilities = params.get("capabilities") if isinstance(params, dict) else None
        self._kinds = isinstance(offered_capabilities, list) and (
            p.TRANSCRIPT_KINDS_CAPABILITY in offered_capabilities
        )
        self._result(
            id_,
            {
                "protocolVersion": chosen,
                "runner": {"name": NAME, "version": __version__},
                "capabilities": [p.TRANSCRIPT_KINDS_CAPABILITY] if self._kinds else [],
            },
        )

    # run/start

    def _start(self, id_: object, params: object) -> None:
        if self._run_id is not None:
            self._error(
                id_,
                p.JSONRPC_REFUSED,
                "runner.already-started",
                f"This runner process is already serving run {self._run_id}.",
                "Start a new runner process for each run.",
            )
            return
        try:
            start = p.RunStartParams.from_data(params)
        except p.ProtocolError as error:
            self._error(
                id_,
                p.JSONRPC_INVALID_PARAMS,
                "runner.invalid-params",
                str(error),
                "Send the run/start params the contract defines.",
            )
            return
        try:
            options = parse_options(start.options)
        except OptionsError as error:
            self._error(
                id_,
                p.JSONRPC_INVALID_PARAMS,
                error.code,
                f"{error.where}: {error.problem}",
                error.fix,
                {"where": error.where},
            )
            return
        try:
            runtime = from_run_start(start, self._environ)
        except RuntimeRefusedError as error:
            self._error(
                id_, p.JSONRPC_INVALID_PARAMS, error.code, error.problem, error.fix, error.details
            )
            return
        try:
            # Made before run/start is answered: it checks the workspace and scratch directory, so
            # a run it can't make is refused, never acknowledged and then dropped.
            tools = Tools.for_declaration(Declaration.from_run_start(start))
        except (OSError, ValueError) as error:
            self._error(
                id_,
                p.JSONRPC_INVALID_PARAMS,
                "runner.invalid-params",
                f"The run's workspace, scratch directory or effects can't be used: {error}",
                "Send a workspace that exists, a scratch directory that exists outside it, and "
                "effects the contract's patterns accept.",
            )
            return
        engine: EngineLike = self._make_engine(runtime.endpoint, runtime.api_host)
        self._set_engine(engine)
        try:
            model = check(engine, runtime, version_tested_with())
        except RefusedError as error:
            engine.close()
            self._error(id_, p.JSONRPC_REFUSED, error.code, error.problem, error.fix, error.details)
            return
        numbering = EventNumbering(
            start.run_id,
            start.limits.event_max_bytes,
            next_seq=1,
            summary_max_bytes=SUMMARY_MAX_BYTES,
        )
        run = Run(
            runtime=runtime,
            options=options,
            tools=tools,
            numbering=numbering,
            engine=engine,
            model=model,
            send=self.event,
            record=self.transcript,
            wait=self._stop.wait,
            stopping=self._stop.is_set,
            make_definitions=tool_definitions,
            sent_tools=sent_tools,
            on_engine=self._set_engine,
        )
        self._run_id = start.run_id
        self._result(id_, {"runId": start.run_id})
        self._worker = threading.Thread(target=self._perform, args=(run, start, tools), daemon=True)
        self._worker.start()

    # The run

    def _init(self, start: p.RunStartParams, model: str, tools: Tools) -> p.InitEvent:
        return p.InitEvent(
            run_id=start.run_id,
            seq=0,
            runner=p.Named(name=NAME, version=__version__),
            tools=tools.names(),
            engine=p.Engine(name=ENGINE, model=model),
            effects="checked",
        )

    def _perform(self, run: Run, start: p.RunStartParams, tools: Tools) -> None:
        try:
            self.event(self._init(start, run.runtime.model, tools))
            if start.on_context_full == "compact":
                # It doesn't compact yet: say so, so the opt-in isn't quietly ignored. A full
                # context still ends the run with context-length (compaction-opt-in design D11).
                run.warn(NO_COMPACTION)
            result = run.run(start.character, start.direction)
            if result is not None:
                self.event(result)
        except Exception as error:  # the runner's own failure: reported, then exit 1
            self._failed = True
            self._diagnose("the run failed:\n" + traceback.format_exc())
            with contextlib.suppress(Exception):
                self.event(
                    run.failure(f"The LM Studio runner failed: {type(error).__name__}: {error}")
                )
        finally:
            with contextlib.suppress(Exception):
                run.engine.close()
            self._inbox.put((_WORKER_DONE, b""))

    # Ending

    def _halt(self) -> None:
        """Stop the run: nothing more from the worker, the engine closed, which ends the
        prediction in flight, and the worker given a moment to finish."""
        with self._out:
            self._stop.set()
        with self._engine_lock:
            engine = self._engine
        if engine is not None:
            with contextlib.suppress(Exception):
                engine.close()
        if self._worker is not None:
            self._worker.join(STOP_GRACE_SECONDS)
            if self._worker.is_alive():
                self._diagnose(f"the run didn't stop within {STOP_GRACE_SECONDS:g}s")

    def _end(self, id_: object, why: str | None) -> NoReturn:
        """Answer run/cancel or shutdown, stop, and exit."""
        with self._out:
            self._stop.set()
        if why is not None:
            self._diagnose(why)
        self._result(id_, {})
        self._halt()
        raise _Exit(1 if self._failed else 0)


NO_COMPACTION = (
    "This run's onContextFull is compact, but the LM Studio runner doesn't compact a conversation "
    "yet: when the model's context fills, the run ends with context-length."
)
"""The warning a run told to compact gets: compacting between act() rounds is a follow-up."""


def main() -> NoReturn:
    code = Runner(sys.stdin.buffer, sys.stdout.buffer, sys.stderr.buffer).run()
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(OSError):
            stream.flush()
    # The reader thread may still be blocked on standard input, and the library's websocket thread
    # may still be closing, either of which would hold up a normal exit at interpreter shutdown.
    os._exit(code)
