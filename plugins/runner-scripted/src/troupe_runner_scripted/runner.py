"""The scripted runner's process: the runner contract over standard input and output (design D12).

A reader thread turns each line of standard input into a message on a queue (end of input is a
message too), so a wait or a hang wakes at once on run/cancel, shutdown or end of input. The main
thread answers the handshake, plays the script and writes every message as one line.
"""

import contextlib
import hashlib
import json
import os
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Any, BinaryIO, Literal, NoReturn

from troupe_plugin_sdk import runner as p
from troupe_plugin_sdk.credential import CredentialError, runtime_credential
from troupe_plugin_sdk.declaration import Declaration
from troupe_plugin_sdk.events import EventNumbering
from troupe_plugin_sdk.tools import Tools
from troupe_runner_scripted import NAME, __version__
from troupe_runner_scripted.script import (
    Options,
    ScriptError,
    Step,
    loads_strict,
    parse_options,
    read_recording,
    workspace_relative,
)

PROTOCOL_VERSIONS = p.PROTOCOL_VERSIONS
INVALID_REQUEST = p.JSONRPC_INVALID_REQUEST
METHOD_NOT_FOUND = p.JSONRPC_METHOD_NOT_FOUND
INVALID_PARAMS = p.JSONRPC_INVALID_PARAMS
PARSE_ERROR = p.JSONRPC_PARSE_ERROR
REFUSED = p.JSONRPC_REFUSED
"""The contract's protocol versions and JSON-RPC error codes are the plugin SDK's (spec:
plugin-sdk; runner-sdk design D4)."""

EOF = object()
"""Put on the queue when standard input reaches end of file."""


class _Exit(Exception):  # noqa: N818 - control flow, not an error
    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


class Runner:
    def __init__(self, stdin: BinaryIO, stdout: BinaryIO, stderr: BinaryIO) -> None:
        self._stdin = stdin
        self._stdout = stdout
        self._stderr = stderr
        self._inbox: queue.Queue[object] = queue.Queue()
        self._write_lock = threading.Lock()
        self._initialized = False
        self._run_id: str | None = None
        self._options: Options | None = None
        self._character: str | None = None
        self._workspace: Path | None = None
        self._params: dict[str, Any] = {}
        self._tools: Tools | None = None
        self._tool_steps = 0
        self._next_seq = 0
        self._cancel_ignored = False

    # Output

    def _send(self, message: dict[str, Any]) -> None:
        line = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
        self._raw(line)

    def _raw(self, data: bytes) -> None:
        with self._write_lock:
            self._stdout.write(data)
            self._stdout.flush()

    def _result(self, id_: object, result: p.Message) -> None:
        self._send({"jsonrpc": "2.0", "id": id_, "result": result.to_data()})

    def _error(
        self,
        id_: object,
        rpc_code: int,
        code: str,
        problem: str,
        fix: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        data = p.ErrorData(code=code, problem=problem, fix=fix, details=details or None)
        error = p.RpcError(code=rpc_code, message=problem, data=data)
        self._send({"jsonrpc": "2.0", "id": id_, "error": error.to_data()})

    # Input

    def _read(self) -> None:
        for line in iter(self._stdin.readline, b""):
            self._inbox.put(line)
        self._inbox.put(EOF)

    def _next(self, timeout: float | None) -> object:
        """The next message, or None if ``timeout`` passed first. Ends the process at EOF."""
        try:
            item = self._inbox.get(timeout=timeout)
        except queue.Empty:
            return None
        if item is EOF:
            raise _Exit(0)
        return item

    def _handle(self, line: object) -> None:
        """Answer one message from troupe."""
        if not isinstance(line, bytes):
            return
        try:
            message = loads_strict(line, "message")
        except ScriptError as error:
            self._error(None, PARSE_ERROR, "runner.parse-error", error.problem, "Send JSON.")
            return
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            self._error(
                None,
                INVALID_REQUEST,
                "runner.invalid-request",
                "Not a JSON-RPC 2.0 request.",
                "Send a JSON-RPC 2.0 request.",
            )
            return
        id_ = message.get("id")
        method = message.get("method")
        params = message.get("params", {})
        if method == "initialize":
            self._initialize(id_, params)
        elif not self._initialized:
            self._error(
                id_,
                INVALID_REQUEST,
                "runner.not-initialized",
                f"{method!r} came before initialize.",
                "Send initialize first.",
            )
        elif method == "run/start":
            self._start(id_, params)
        elif method == "run/cancel":
            self._cancel(id_)
        elif method == "shutdown":
            self._result(id_, p.Empty())
            raise _Exit(0)
        else:
            self._error(
                id_,
                METHOD_NOT_FOUND,
                "runner.unknown-method",
                f"The scripted runner doesn't know the method {method!r}.",
                "Use a method of the runner contract.",
            )

    def _initialize(self, id_: object, params: Any) -> None:  # noqa: ANN401
        offered = params.get("protocolVersions") if isinstance(params, dict) else None
        if not isinstance(offered, list) or not any(v in PROTOCOL_VERSIONS for v in offered):
            self._error(
                id_,
                REFUSED,
                "runner.unsupported-version",
                f"The scripted runner supports protocol version(s) {list(PROTOCOL_VERSIONS)}, "
                f"none of which was offered ({offered!r}).",
                "Offer a protocol version this runner supports.",
                {"supportedVersions": list(PROTOCOL_VERSIONS)},
            )
            return
        self._initialized = True
        chosen = max(v for v in offered if v in PROTOCOL_VERSIONS)
        self._result(
            id_,
            p.InitializeResult(
                protocol_version=chosen,
                runner=p.Named(name=NAME, version=__version__),
                capabilities=[],
            ),
        )

    def _start(self, id_: object, params: Any) -> None:  # noqa: ANN401
        if self._run_id is not None:
            self._error(
                id_,
                REFUSED,
                "runner.already-started",
                f"This runner process is already serving run {self._run_id}.",
                "Start a new runner process for each run.",
            )
            return
        if not isinstance(params, dict) or not isinstance(params.get("runId"), str):
            self._error(
                id_,
                INVALID_PARAMS,
                "runner.invalid-params",
                "run/start needs a runId.",
                "Send the run/start params the contract defines.",
            )
            return
        workspace = Path(str(params.get("workspace", "")))
        try:
            self._options = parse_options(params.get("options"), workspace)
        except ScriptError as error:
            self._error(
                id_,
                INVALID_PARAMS,
                error.code,
                f"{error.where}: {error.problem}",
                "Fix the script or options as named, then start the run again.",
                {"where": error.where},
            )
            return
        self._run_id = params["runId"]
        self._workspace = workspace
        character = params.get("character")
        self._character = character if isinstance(character, str) else None
        self._params = params
        self._result(id_, p.RunStartResult(run_id=self._run_id))

    def _cancel(self, id_: object) -> None:
        self._result(id_, p.Empty())
        if self._options is None:
            raise _Exit(0)
        mode = self._options.script.on_cancel
        if mode == "honour":
            raise _Exit(0)
        if mode == "honour-with-result":
            self._result_event("cancelled")
            raise _Exit(0)
        self._cancel_ignored = True

    # Playing

    def _event(self, event: dict[str, Any]) -> None:
        sent = {"runId": self._run_id, **event}
        if "seq" not in event:
            sent["seq"] = self._next_seq
        self._next_seq = int(sent["seq"]) + 1 if isinstance(sent["seq"], int) else self._next_seq
        self._send({"jsonrpc": "2.0", "method": "run/event", "params": sent})

    def _transcript(self, record: str, encoding: Literal["utf-8", "base64"] | None = None) -> None:
        params = p.TranscriptRecord(run_id=self._started_run(), record=record, encoding=encoding)
        self._send(p.notification("run/transcript", params))

    def _started_run(self) -> str:
        if self._run_id is None:
            raise RuntimeError("a step played before run/start")
        return self._run_id

    def _result_event(self, message: str) -> None:
        """End the run with an error result, built with the SDK's type."""
        seq, self._next_seq = self._next_seq, self._next_seq + 1
        event = p.ResultEvent(run_id=self._started_run(), seq=seq, status="error", message=message)
        self._send(p.notification("run/event", event))

    def _pause(self, seconds: float) -> None:
        """Wait ``seconds``, still answering troupe: cancel, shutdown or EOF can end it early."""
        deadline = time.monotonic() + seconds
        while (left := deadline - time.monotonic()) > 0:
            message = self._next(left)
            if message is not None:
                self._handle(message)

    def _play(self, step: Step) -> None:
        kind, value = step.kind, step.value
        if kind == "event":
            event = dict(value)
            if event.get("type") == "init":
                # It checks every tool step's call with the SDK's tools (declared-effects D9).
                event.setdefault("effects", "checked")
            self._event(event)
        elif kind == "transcript":
            if isinstance(value, dict):
                self._transcript(value["record"], value.get("encoding"))
            else:
                self._transcript(value)
        elif kind == "stderr":
            self._stderr.write(value.encode())
            self._stderr.flush()
        elif kind == "rawStdout":
            self._raw(value.encode() + b"\n")
        elif kind == "wait":
            self._pause(value["ms"] / 1000)
        elif kind == "writeFile":
            workspace = self._started()[1]
            target = workspace.joinpath(*workspace_relative(value["path"], "writeFile").parts)
            if not target.resolve().is_relative_to(workspace.resolve()):
                raise _Exit(self._refuse_escape(value["path"]))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(value["content"].encode())
        elif kind == "hang":
            while True:
                self._handle(self._next(None))
        elif kind == "exit":
            raise _Exit(value)
        elif kind == "replay":
            self._replay(value)
        elif kind == "checkCharacter":
            self._check_character(value)
        elif kind == "checkRuntime":
            self._check_runtime(value)
        elif kind == "echoCredential":
            self._echo_credential()
        elif kind == "tool":
            self._tool(value)

    def _tool(self, value: dict[str, Any]) -> None:
        """Carry out one call with the SDK's tools for run/start's declaration, send its two
        events, and end the run with an error result when it was to be (or not be) an error
        (declared-effects design D9)."""
        self._tool_steps += 1
        tools = self._tools_for_run()
        limits = self._params.get("limits", {})
        numbering = EventNumbering(
            self._started_run(), int(limits.get("eventMaxBytes", 65536)), self._next_seq
        )
        call_id = value.get("callId", f"tool-{self._tool_steps}")
        step = tools.run(call_id, value["name"], value["input"], numbering)
        for event in step.events:
            self._event(event.to_data())
        wanted = value.get("isError")
        if wanted is not None and wanted != step.is_error:
            said = "an error" if step.is_error else "not an error"
            self._result_event(
                f"tool step {self._tool_steps} ({value['name']}, call {call_id}): its result was "
                f"{said}, which the script didn't expect: {step.output}"
            )
            raise _Exit(0)

    def _tools_for_run(self) -> Tools:
        if self._tools is None:
            self._tools = Tools.for_declaration(
                Declaration.from_run_start(p.RunStartParams.from_data(self._params))
            )
        return self._tools

    def _check_character(self, value: dict[str, Any]) -> None:
        """End the run with an error result unless run/start's character is the one expected."""
        got = (
            "none"
            if self._character is None
            else "sha256:" + hashlib.sha256(self._character.encode("utf-8")).hexdigest()
        )
        wanted = value.get("hash", "none")
        if got != wanted:
            self._result_event(
                f"the character run/start carried is {got}; the script expected {wanted}"
            )
            raise _Exit(0)

    def _credential(self) -> str | None:
        """The run's credential, as the SDK reads it; a disagreement ends the run."""
        try:
            return runtime_credential(p.RunStartParams.from_data(self._params), os.environ)
        except CredentialError as error:
            self._result_event(f"the run's credential: {error}")
            raise _Exit(0) from error

    def _check_runtime(self, value: dict[str, Any]) -> None:
        """End the run with an error result unless run/start's runtime, and the credential in the
        environment, are the ones expected. A credential is only ever named by its hash."""
        runtime = self._params.get("runtime")
        if value.get("absent") is True:
            if runtime is not None:
                self._result_event(
                    f"run/start carried the runtime {runtime.get('name')!r}; "
                    "the script expected none"
                )
                raise _Exit(0)
            return
        if not isinstance(runtime, dict):
            self._result_event("run/start carried no runtime; the script expected one")
            raise _Exit(0)
        differs = [
            f"{field}: run/start carried {runtime.get(field)!r}, the script expected "
            f"{value[field]!r}"
            for field in ("name", "endpoint", "model")
            if field in value and runtime.get(field) != value[field]
        ]
        if "credentialHash" in value or "noCredential" in value:
            wanted = value.get("credentialHash")
            credential = self._credential()
            got = (
                None
                if credential is None
                else "sha256:" + hashlib.sha256(credential.encode("utf-8")).hexdigest()
            )
            if got != wanted:
                differs.append(
                    f"credential: the environment held {got or 'none'}, the script expected "
                    f"{wanted or 'none'}"
                )
        if differs:
            self._result_event("the runtime differs: " + "; ".join(differs))
            raise _Exit(0)

    def _echo_credential(self) -> None:
        """Send the run's credential back in a log event, a transcript record and standard error,
        as a runner that leaks it would, so a test can show what troupe keeps. Only for tests."""
        credential = self._credential()
        if credential is None:
            self._result_event("an echoCredential step needs a credential, and the run has none")
            raise _Exit(0)
        self._event({"type": "log", "level": "info", "message": f"the key is {credential}"})
        self._transcript(json.dumps({"key": credential}))
        self._stderr.write(f"the key is {credential}\n".encode())
        self._stderr.flush()

    def _started(self) -> tuple[Options, Path]:
        if self._options is None or self._workspace is None:
            raise RuntimeError("a step played before run/start")
        return self._options, self._workspace

    def _refuse_escape(self, path: str) -> int:
        self._stderr.write(f"scripted runner: {path!r} resolves outside the workspace\n".encode())
        self._stderr.flush()
        return 2

    def _replay(self, path_text: str) -> None:
        options = self._started()[0]
        path = Path(path_text)
        if not path.is_absolute():
            path = options.base / path
        try:
            records = read_recording(path)
        except ScriptError as error:
            self._stderr.write(f"scripted runner: {error}\n".encode())
            self._stderr.flush()
            raise _Exit(2) from error
        started = time.monotonic()
        for record in records:
            if options.replay_delays and record.at_ms is not None:
                self._pause(max(0.0, started + record.at_ms / 1000 - time.monotonic()))
            if record.event is not None:
                self._event({**record.event, "runId": self._run_id})
            elif record.transcript is not None:
                self._transcript(record.transcript)

    def serve(self) -> int:
        threading.Thread(target=self._read, daemon=True).start()
        try:
            while self._options is None:
                self._handle(self._next(None))
            # Steps that don't wait play back to back. Troupe's messages are answered where a step
            # waits (a wait, a replay's delays, a hang) and after the last step, so a script plays
            # the same way whenever they arrive (spec: scripted-runner).
            for step in self._options.script.steps:
                self._play(step)
            while True:
                self._handle(self._next(None))
        except _Exit as done:
            return done.code


def main() -> NoReturn:
    code = Runner(sys.stdin.buffer, sys.stdout.buffer, sys.stderr.buffer).serve()
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(OSError):
            stream.flush()
    os._exit(code)  # the reader thread may still be blocked on standard input


__all__ = ["Runner", "main"]
