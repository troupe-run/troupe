"""The scripted runner's process: the runner contract over standard input and output (design D12).

A reader thread turns each line of standard input into a message on a queue (end of input is a
message too), so a wait or a hang wakes at once on run/cancel, shutdown or end of input. The main
thread answers the handshake, plays the script and writes every message as one line.
"""

import contextlib
import json
import os
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Any, BinaryIO, NoReturn

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

PROTOCOL_VERSIONS = (1,)
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
PARSE_ERROR = -32700
REFUSED = -32000

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
        self._workspace: Path | None = None
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

    def _result(self, id_: object, result: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "id": id_, "result": result})

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
        if details:
            data["details"] = details
        self._send(
            {
                "jsonrpc": "2.0",
                "id": id_,
                "error": {"code": rpc_code, "message": problem, "data": data},
            }
        )

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
            self._result(id_, {})
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
            {
                "protocolVersion": chosen,
                "runner": {"name": NAME, "version": __version__},
                "capabilities": [],
            },
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
        self._result(id_, {"runId": self._run_id})

    def _cancel(self, id_: object) -> None:
        self._result(id_, {})
        if self._options is None:
            raise _Exit(0)
        mode = self._options.script.on_cancel
        if mode == "honour":
            raise _Exit(0)
        if mode == "honour-with-result":
            self._event({"type": "result", "status": "error", "message": "cancelled"})
            raise _Exit(0)
        self._cancel_ignored = True

    # Playing

    def _event(self, event: dict[str, Any]) -> None:
        sent = {"runId": self._run_id, **event}
        if "seq" not in event:
            sent["seq"] = self._next_seq
        self._next_seq = int(sent["seq"]) + 1 if isinstance(sent["seq"], int) else self._next_seq
        self._send({"jsonrpc": "2.0", "method": "run/event", "params": sent})

    def _transcript(self, record: str, encoding: str | None = None) -> None:
        params: dict[str, Any] = {"runId": self._run_id, "record": record}
        if encoding is not None:
            params["encoding"] = encoding
        self._send({"jsonrpc": "2.0", "method": "run/transcript", "params": params})

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
            self._event(dict(value))
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
            else:
                self._drain()
            if record.event is not None:
                self._event({**record.event, "runId": self._run_id})
            elif record.transcript is not None:
                self._transcript(record.transcript)

    def _drain(self) -> None:
        """Answer anything troupe has sent, without waiting."""
        while (message := self._next(0)) is not None:
            self._handle(message)

    def serve(self) -> int:
        threading.Thread(target=self._read, daemon=True).start()
        try:
            while self._options is None:
                self._handle(self._next(None))
            for step in self._options.script.steps:
                self._drain()
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
