"""The Claude Code runner's process: the runner contract over standard input and output (design
D2, D7).

Threads turn troupe's lines and Claude Code's lines into items on one queue (each end of input is
an item too). The main thread is the only one that writes to standard output, so every state
change happens between two lines, never inside one. Before run/start is answered, everything that
can be refused is checked: the options, finding claude, and the private directory. After it,
Claude Code starts and every line it writes goes through the mapper.

The runner never exits while Claude Code is running, and it never invents a result.
"""

import contextlib
import json
import os
import queue
import shutil
import sys
import threading
from pathlib import Path
from typing import Any, BinaryIO, NoReturn

from troupe_runner_claude_code import NAME, __version__
from troupe_runner_claude_code.command import (
    PrivateDirectoryError,
    build,
    make_private_directory,
)
from troupe_runner_claude_code.defaults import CLAUDE_EXIT_WAIT_SECONDS, CLAUDE_STOP_GRACE_SECONDS
from troupe_runner_claude_code.mapping import (
    Event,
    Mapper,
    NotJsonError,
    Out,
    Transcript,
    loads_strict,
)
from troupe_runner_claude_code.options import OptionsError, parse_options
from troupe_runner_claude_code.processes import Claude, exit_code, find_claude, start

PROTOCOL_VERSIONS = (0,)
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
PARSE_ERROR = -32700
REFUSED = -32000

_TROUPE = "troupe"
_TROUPE_EOF = "troupe-eof"
_ENGINE = "engine"
_ENGINE_EOF = "engine-eof"


class _Exit(Exception):  # noqa: N818 - control flow, not an error
    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


def _strip_line_ending(line: bytes) -> bytes:
    if line.endswith(b"\n"):
        line = line[:-1]
        if line.endswith(b"\r"):
            line = line[:-1]
    return line


class Runner:
    def __init__(self, stdin: BinaryIO, stdout: BinaryIO, stderr: BinaryIO) -> None:
        self._stdin = stdin
        self._stdout = stdout
        self._stderr = stderr
        self._inbox: queue.Queue[tuple[str, bytes]] = queue.Queue()
        self._stderr_lock = threading.Lock()
        self._initialized = False
        self._run_id: str | None = None
        self._next_seq = 0
        self._mapper: Mapper | None = None
        self._claude: Claude | None = None
        self._claude_status: int | None = None
        self._engine_done = False
        self._private: Path | None = None
        self._cancelled = False

    # Output

    def _send(self, message: dict[str, Any]) -> None:
        line = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
        self._stdout.write(line)
        self._stdout.flush()

    def _diagnose(self, text: str) -> None:
        with self._stderr_lock:
            self._stderr.write(f"claude-code runner: {text}\n".encode())
            self._stderr.flush()

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
        if details is not None:
            data["details"] = details
        self._send(
            {
                "jsonrpc": "2.0",
                "id": id_,
                "error": {"code": rpc_code, "message": problem, "data": data},
            }
        )

    def _emit(self, outs: list[Out]) -> None:
        for out in outs:
            if isinstance(out, Transcript):
                params: dict[str, Any] = {"runId": self._run_id, "record": out.record}
                if out.encoding is not None:
                    params["encoding"] = out.encoding
                self._send({"jsonrpc": "2.0", "method": "run/transcript", "params": params})
            elif isinstance(out, Event):
                event = {"runId": self._run_id, "seq": self._next_seq, **out.event}
                self._next_seq += 1
                self._send({"jsonrpc": "2.0", "method": "run/event", "params": event})

    # Input

    def _read_troupe(self) -> None:
        for line in iter(self._stdin.readline, b""):
            self._inbox.put((_TROUPE, line))
        self._inbox.put((_TROUPE_EOF, b""))

    def _read_engine(self, stream: BinaryIO) -> None:
        for line in iter(stream.readline, b""):
            self._inbox.put((_ENGINE, _strip_line_ending(line)))
        self._inbox.put((_ENGINE_EOF, b""))

    def _forward_stderr(self, stream: BinaryIO) -> None:
        while chunk := stream.read1(65536):  # type: ignore[attr-defined]
            with self._stderr_lock:
                self._stderr.write(chunk)
                self._stderr.flush()

    def _feed_stdin(self, stream: BinaryIO, data: bytes) -> None:
        with contextlib.suppress(OSError):  # Claude Code may exit without reading it all
            stream.write(data)
        with contextlib.suppress(OSError):
            stream.close()

    def _next(self, timeout: float | None = None) -> tuple[str, bytes] | None:
        try:
            return self._inbox.get(timeout=timeout)
        except queue.Empty:
            return None

    # troupe's messages

    def _handle(self, line: bytes) -> None:
        try:
            message = loads_strict(line.decode("utf-8"))
        except (UnicodeDecodeError, NotJsonError) as error:
            self._error(
                None,
                PARSE_ERROR,
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
                INVALID_REQUEST,
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
                INVALID_REQUEST,
                "runner.not-initialized",
                f"{method!r} came before initialize.",
                "Send initialize first.",
            )
        elif method == "run/start":
            self._start(id_, params)
        elif method == "run/cancel":
            self._result(id_, {})
            self._cancel()
        elif method == "shutdown":
            self._shutdown(id_)
        else:
            self._error(
                id_,
                METHOD_NOT_FOUND,
                "runner.unknown-method",
                f"The Claude Code runner doesn't know the method {method!r}.",
                "Use a method of the runner contract.",
            )

    def _initialize(self, id_: object, params: object) -> None:
        offered = params.get("protocolVersions") if isinstance(params, dict) else None
        if not isinstance(offered, list) or not any(v in PROTOCOL_VERSIONS for v in offered):
            self._error(
                id_,
                REFUSED,
                "runner.unsupported-version",
                f"The Claude Code runner supports protocol version(s) {list(PROTOCOL_VERSIONS)}, "
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

    def _invalid_params(self, id_: object, problem: str) -> None:
        self._error(
            id_,
            INVALID_PARAMS,
            "runner.invalid-params",
            problem,
            "Send the run/start params the contract defines.",
        )

    def _start(self, id_: object, params: object) -> None:
        if self._run_id is not None:
            self._error(
                id_,
                REFUSED,
                "runner.already-started",
                f"This runner process is already serving run {self._run_id}.",
                "Start a new runner process for each run.",
            )
            return
        if not isinstance(params, dict):
            self._invalid_params(id_, "run/start's params aren't an object.")
            return
        run_id, direction = params.get("runId"), params.get("direction")
        workspace_text, limits = params.get("workspace"), params.get("limits")
        character = params.get("character")
        limit = limits.get("eventMaxBytes") if isinstance(limits, dict) else None
        if not (
            isinstance(run_id, str)
            and isinstance(direction, str)
            and isinstance(workspace_text, str)
            and isinstance(limit, int)
            and not isinstance(limit, bool)
            and limit > 0
            and (character is None or isinstance(character, str))
        ):
            self._invalid_params(
                id_,
                "run/start needs a runId, a direction, a workspace and limits.eventMaxBytes, and a "
                "character only as a string.",
            )
            return
        try:
            options = parse_options(params.get("options", {}))
        except OptionsError as error:
            self._error(
                id_,
                INVALID_PARAMS,
                error.code,
                f"{error.where}: {error.problem}",
                error.fix,
                {"where": error.where},
            )
            return
        path = os.environ.get("PATH")
        claude = find_claude(path)
        if claude is None:
            self._error(
                id_,
                REFUSED,
                "claude-code.not-found",
                "There's no claude program on the PATH the runner was given"
                + (f" ({path})." if path else " (it was given no PATH)."),
                "Install Claude Code (https://code.claude.com), and make sure troupe passes the "
                "PATH it's on to the runner.",
                {"path": path} if path else {},
            )
            return
        workspace = Path(workspace_text)
        if not workspace.is_dir():
            self._error(
                id_,
                REFUSED,
                "claude-code.start-failed",
                f"The workspace {workspace_text!r} isn't a directory.",
                "Start the run in a workspace that exists.",
                {"where": workspace_text},
            )
            return
        try:
            private = make_private_directory(workspace)
        except PrivateDirectoryError as error:
            self._error(
                id_,
                REFUSED,
                "claude-code.start-failed",
                error.problem,
                "Point TMPDIR (TEMP on Windows) at a writable directory outside the workspace.",
                {"where": error.where},
            )
            return
        self._private = private
        self._run_id = run_id
        self._mapper = Mapper(__version__, limit)
        self._result(id_, {"runId": run_id})
        launch = build(claude, options, direction, character, private, dict(os.environ))
        self._diagnose(f"running {claude}")
        try:
            self._claude = start(launch.argv, workspace, launch.env)
        except OSError as error:
            self._emit(
                self._mapper.cannot_start(f"Claude Code couldn't be started ({claude}): {error}")
            )
            raise _Exit(1) from error
        process = self._claude.process
        if process.stdin is None or process.stdout is None or process.stderr is None:
            raise RuntimeError("Claude Code was started without its pipes")
        threading.Thread(
            target=self._feed_stdin, args=(process.stdin, launch.stdin), daemon=True
        ).start()
        threading.Thread(target=self._read_engine, args=(process.stdout,), daemon=True).start()
        threading.Thread(target=self._forward_stderr, args=(process.stderr,), daemon=True).start()

    # Ending

    def _stop_claude(self) -> None:
        """Stop Claude Code if it's still running, and wait until it has ended."""
        if self._claude is None or self._claude_status is not None:
            return
        self._claude_status = self._claude.stop(CLAUDE_STOP_GRACE_SECONDS)
        self._claude.release()

    def _wait_claude(self) -> None:
        """Wait for Claude Code to exit on its own, then stop it if it hasn't."""
        if self._claude is None or self._claude_status is not None:
            return
        status = self._claude.wait(CLAUDE_EXIT_WAIT_SECONDS)
        if status is None:
            self._diagnose(
                f"Claude Code was still running {CLAUDE_EXIT_WAIT_SECONDS:g}s after its output "
                "ended; stopping it"
            )
            self._stop_claude()
        else:
            self._claude_status = status
            self._claude.release()

    def _drain(self, timeout: float) -> None:
        """Pass on what Claude Code still writes until its output ends, or ``timeout`` passes."""
        while not self._engine_done:
            item = self._next(timeout)
            if item is None:
                return
            kind, data = item
            if kind == _ENGINE:
                self._on_engine_line(data)
            elif kind == _ENGINE_EOF:
                self._engine_done = True

    def _cancel(self) -> NoReturn:
        """Stop Claude Code and exit, sending no more events: the run was cancelled, or troupe went
        away. Exiting 0 is safe: a run with no result can't succeed."""
        self._cancelled = True
        if self._mapper is not None:
            self._mapper.silence()
        self._stop_claude()
        self._drain(CLAUDE_STOP_GRACE_SECONDS)
        self._report_exit()
        raise _Exit(0)

    def _shutdown(self, id_: object) -> NoReturn:
        """Answer shutdown once Claude Code has exited, then exit with its code."""
        reported = self._engine_done
        self._wait_claude()
        self._drain(CLAUDE_STOP_GRACE_SECONDS)
        if not reported:
            self._report_exit()
        self._result(id_, {})
        raise _Exit(self._exit_code())

    def _exit_code(self) -> int:
        if self._claude is None:
            return 0
        return exit_code(self._claude_status if self._claude_status is not None else 1)

    def _report_exit(self) -> None:
        if self._claude is None or self._claude_status is None:
            return
        sent = self._mapper is not None and self._mapper.result_sent
        self._diagnose(
            f"Claude Code exited with code {self._claude_status}"
            + ("" if sent or self._cancelled else " and sent no result")
        )

    # Claude Code's output

    def _started_mapper(self) -> Mapper:
        if self._mapper is None:
            raise RuntimeError("Claude Code's output arrived before run/start")
        return self._mapper

    def _on_engine_line(self, line: bytes) -> None:
        self._emit(self._started_mapper().feed(line))

    def _on_engine_eof(self) -> None:
        mapper = self._started_mapper()
        self._engine_done = True
        self._wait_claude()
        self._report_exit()
        if not mapper.result_sent:
            self._emit(mapper.finish(self._claude_status))
            raise _Exit(self._exit_code() or 1)

    def serve(self) -> int:
        threading.Thread(target=self._read_troupe, daemon=True).start()
        try:
            while True:
                kind, data = self._inbox.get()
                if kind == _TROUPE:
                    self._handle(data)
                elif kind == _TROUPE_EOF:
                    self._cancel()
                elif kind == _ENGINE:
                    self._on_engine_line(data)
                elif kind == _ENGINE_EOF:
                    self._on_engine_eof()
        except _Exit as done:
            return done.code
        finally:
            self._stop_claude()
            if self._private is not None:
                shutil.rmtree(self._private, ignore_errors=True)


def main() -> NoReturn:
    code = Runner(sys.stdin.buffer, sys.stdout.buffer, sys.stderr.buffer).serve()
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(OSError):
            stream.flush()
    os._exit(code)  # the reader threads may still be blocked on their pipes


__all__ = ["Runner", "main"]
