"""The Anthropic runner's process: the runner contract over standard input and output
(anthropic-runner design D9).

The main thread reads troupe's messages and answers them. Before it answers run/start, it checks
everything that can be refused: the params, the options, the runtime and its credential, and the
workspace. After it answers, a worker thread sends init and runs the tool loop to its result.

Both threads write to standard output, one whole line at a time under one lock, and every line goes
through the run's Mask first, so nothing the runner sends can hold the credential. Stopping (on
run/cancel, end of input or shutdown) sets a flag under that same lock before the answer is
written, so nothing the worker sends can follow it.

A request in flight can't be abandoned from another thread: closing the library's stream or its
HTTP client doesn't interrupt a read in progress (the probe, design D9). So when the run stops with
a request in flight, the runner answers, flushes, and ends its own process, which closes the
connection; a runner process holds one run, so nothing else is lost. Between requests the worker
stops at its next check, within the named grace.
"""

import base64
import contextlib
import json
import os
import queue
import sys
import threading
import traceback
from typing import Any, BinaryIO, NoReturn

from troupe_plugin_sdk import runner as p
from troupe_plugin_sdk.declaration import Declaration
from troupe_plugin_sdk.events import EventNumbering
from troupe_plugin_sdk.tools import Tools
from troupe_runner_anthropic import NAME, __version__
from troupe_runner_anthropic.defaults import STOP_GRACE_SECONDS, SUMMARY_MAX_BYTES
from troupe_runner_anthropic.loop import Loop
from troupe_runner_anthropic.masking import Mask
from troupe_runner_anthropic.options import OptionsError, parse_options
from troupe_runner_anthropic.runtime import Runtime, RuntimeRefusedError, from_run_start
from troupe_runner_anthropic.service import Service, quiet_library_logging

ENGINE = "messages"
"""The engine the init event names: the API the runner speaks, whichever service serves it."""

_TROUPE = "troupe"
_TROUPE_EOF = "troupe-eof"
_WORKER_DONE = "worker-done"


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


class Runner:
    def __init__(
        self,
        stdin: BinaryIO,
        stdout: BinaryIO,
        stderr: BinaryIO,
        environ: dict[str, str] | None = None,
    ) -> None:
        self._stdin = stdin
        self._stdout = stdout
        self._stderr = stderr
        self._environ = dict(os.environ) if environ is None else environ
        self._inbox: queue.Queue[tuple[str, bytes]] = queue.Queue()
        self._out = threading.Lock()
        self._stop = threading.Event()
        self._mask = Mask(None)
        self._kinds = False
        """Whether troupe offered transcript-kinds, which this runner then accepts."""
        self._initialized = False
        self._run_id: str | None = None
        self._worker: threading.Thread | None = None
        self._in_flight = False
        """Whether a request is in flight, set under the output lock."""
        self._service: Service | None = None
        self._failed = False

    # Output

    def _write(self, message: dict[str, Any], *, from_worker: bool = False) -> bool:
        """Write one message as one line, masked. A message from the worker is dropped once the
        run is stopping; False when it was."""
        masked = self._mask.json(message)
        # backslashreplace: a lone surrogate becomes its JSON escape, so no write can fail after
        # an event's seq was taken.
        text = json.dumps(masked, ensure_ascii=False, separators=(",", ":"))
        line = text.encode("utf-8", "backslashreplace") + b"\n"
        with self._out:
            if from_worker and self._stop.is_set():
                return False
            self._stdout.write(line)
            self._stdout.flush()
            return True

    def _diagnose(self, text: str) -> None:
        line = self._mask(f"anthropic runner: {text}\n")
        self._stderr.write(line.encode("utf-8", "backslashreplace"))
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

    # What the loop reports through

    def event(self, event: p.RunEvent) -> None:
        self._write(
            {"jsonrpc": "2.0", "method": "run/event", "params": event.to_data()}, from_worker=True
        )

    def transcript(self, kind: p.TranscriptKind, data: bytes) -> None:
        """Send one transcript record: its kind only when troupe offered transcript-kinds, and
        its bytes as text, or as base64 when they aren't UTF-8. Base64 hides the credential from
        the masking every message gets, so those bytes are masked first."""
        params: dict[str, Any] = {"runId": self._run_id}
        try:
            params["record"] = data.decode("utf-8")
        except UnicodeDecodeError:
            masked = self._mask(data.decode("utf-8", "surrogateescape"))
            params["record"] = base64.b64encode(masked.encode("utf-8", "surrogateescape")).decode()
            params["encoding"] = "base64"
        if self._kinds:
            params["kind"] = kind
        self._write(
            {"jsonrpc": "2.0", "method": "run/transcript", "params": params}, from_worker=True
        )

    def _begin(self) -> bool:
        """A request is about to go out: False, sending nothing, when the run is stopping."""
        with self._out:
            if self._stop.is_set():
                return False
            self._in_flight = True
            return True

    def _end_request(self) -> None:
        with self._out:
            self._in_flight = False

    # Input

    def _read_troupe(self) -> None:
        for line in iter(self._stdin.readline, b""):
            self._inbox.put((_TROUPE, line))
        self._inbox.put((_TROUPE_EOF, b""))

    def run(self) -> int:
        """Serve troupe until the run ends; the exit code."""
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
                f"The Anthropic runner doesn't know the method {method!r}.",
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
                f"The Anthropic runner supports protocol version(s) "
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
        # From here on, everything the runner sends is masked for this run's credential.
        self._mask = Mask(runtime.credential)
        quiet_library_logging(self._mask, _TextOut(self._stderr))
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
        numbering = EventNumbering(
            start.run_id,
            start.limits.event_max_bytes,
            next_seq=1,
            summary_max_bytes=SUMMARY_MAX_BYTES,
        )
        self._service = self._make_service(runtime)
        loop = Loop(
            runtime=runtime,
            options=options,
            tools=tools,
            numbering=numbering,
            open=self._service.stream,
            send=self.event,
            record=self.transcript,
            wait=self._stop.wait,
            begin=self._begin,
            end=self._end_request,
            stopping=self._stop.is_set,
            compact=start.on_context_full == "compact",
        )
        self._run_id = start.run_id
        self._result(id_, {"runId": start.run_id})
        self._worker = threading.Thread(
            target=self._perform, args=(loop, start, runtime, tools), daemon=True
        )
        self._worker.start()

    # The run

    def _init(self, start: p.RunStartParams, runtime: Runtime, tools: Tools) -> p.InitEvent:
        return p.InitEvent(
            run_id=start.run_id,
            seq=0,
            runner=p.Named(name=NAME, version=__version__),
            tools=tools.names(),
            engine=p.Engine(name=ENGINE, model=runtime.model),
            effects="checked",
        )

    def _perform(self, loop: Loop, start: p.RunStartParams, runtime: Runtime, tools: Tools) -> None:
        try:
            self.event(self._init(start, runtime, tools))
            result = loop.run(start.direction, start.character)
            if result is not None:
                self.event(result)
        except Exception as error:  # the runner's own failure: reported, then exit 1
            self._failed = True
            self._diagnose("the run failed:\n" + traceback.format_exc())
            with contextlib.suppress(Exception):
                self.event(
                    loop.failure(f"The Anthropic runner failed: {type(error).__name__}: {error}")
                )
        finally:
            self._inbox.put((_WORKER_DONE, b""))

    # Ending

    def _halt(self) -> None:
        """Stop the run: nothing more from the worker, and the worker given a moment to finish
        between requests. With a request in flight, the process ends instead (main's os._exit),
        which closes its connection (design D9)."""
        with self._out:
            self._stop.set()
            in_flight = self._in_flight
        if in_flight:
            self._diagnose("ending the process to abandon the request in flight")
            return
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

    @staticmethod
    def _make_service(runtime: Runtime) -> Service:
        return Service(runtime)


class _TextOut:
    """A text stream over a binary one, for the library's warnings on standard error."""

    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream

    def write(self, text: str) -> int:
        self._stream.write(text.encode("utf-8", "backslashreplace"))
        return len(text)

    def flush(self) -> None:
        self._stream.flush()


def main() -> NoReturn:
    code = Runner(sys.stdin.buffer, sys.stdout.buffer, sys.stderr.buffer).run()
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(OSError):
            stream.flush()
    # The reader thread may still be blocked on standard input, which would abort a normal exit
    # at interpreter shutdown; the other runners exit the same way.
    os._exit(code)
