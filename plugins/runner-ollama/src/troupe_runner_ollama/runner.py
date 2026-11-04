"""The Ollama runner's process: the runner contract over standard input and output
(local-model-runner design D3, D4).

The main thread reads troupe's messages and answers them. Before it answers run/start, it checks
everything that can be refused: the params, the options, and the preflight (Ollama answers, its
version meets the runner's published requirements, the model is there and can call tools, and the
context window fits it). After it answers, a worker thread runs the conversation.

Both threads write to standard output, one whole line at a time under one lock. Stopping (on
run/cancel, end of input or shutdown) sets a flag under that same lock before the answer is
written, so nothing the worker sends can follow it. Then the request in flight is closed, which
wakes the worker wherever it waits.
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
from troupe_runner_ollama import NAME, __version__
from troupe_runner_ollama.client import Client, StoppedError, UnreachableError
from troupe_runner_ollama.conversation import Conversation
from troupe_runner_ollama.defaults import (
    DEFAULT_CONTEXT_LENGTH,
    PREFLIGHT_TIMEOUT_SECONDS,
    STOP_GRACE_SECONDS,
)
from troupe_runner_ollama.options import Options, OptionsError, parse_options
from troupe_runner_ollama.requirements import check, load

_TROUPE = "troupe"
_TROUPE_EOF = "troupe-eof"
_WORKER_DONE = "worker-done"


class _Exit(Exception):  # noqa: N818 - control flow, not an error
    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


class _Refused(Exception):  # noqa: N818 - a refusal to answer with, not the runner's error
    """run/start is refused with this error."""

    def __init__(
        self, rpc_code: int, code: str, problem: str, fix: str, details: dict[str, Any]
    ) -> None:
        super().__init__(problem)
        self.rpc_code = rpc_code
        self.code = code
        self.problem = problem
        self.fix = fix
        self.details = details


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


def model_maximum(shown: dict[str, Any]) -> int | None:
    """The model's own maximum context, from /api/show's ``model_info``, or None when Ollama
    doesn't say (design D4)."""
    info = shown.get("model_info")
    if not isinstance(info, dict):
        return None
    architecture = info.get("general.architecture")
    if not isinstance(architecture, str):
        return None
    value = info.get(f"{architecture}.context_length")
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


class Runner:
    def __init__(self, stdin: BinaryIO, stdout: BinaryIO, stderr: BinaryIO) -> None:
        self._stdin = stdin
        self._stdout = stdout
        self._stderr = stderr
        self._inbox: queue.Queue[tuple[str, bytes]] = queue.Queue()
        self._out = threading.Lock()
        self._stop = threading.Event()
        self._initialized = False
        self._run_id: str | None = None
        self._client: Client | None = None
        self._worker: threading.Thread | None = None
        self._failed = False

    # Output

    def _write(self, message: dict[str, Any], *, from_worker: bool = False) -> bool:
        """Write one message as one line. A message from the worker is dropped once the run is
        stopping; False when it was."""
        line = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
        with self._out:
            if from_worker and self._stop.is_set():
                return False
            self._stdout.write(line)
            self._stdout.flush()
            return True

    def _diagnose(self, text: str) -> None:
        self._stderr.write(f"ollama runner: {text}\n".encode())
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

    # The sink the conversation reports through

    def event(self, event: p.RunEvent) -> None:
        self._write(
            {"jsonrpc": "2.0", "method": "run/event", "params": event.to_data()}, from_worker=True
        )

    def transcript(self, record: bytes) -> None:
        params: dict[str, Any] = {"runId": self._run_id}
        try:
            params["record"] = record.decode("utf-8")
        except UnicodeDecodeError:
            params["record"] = base64.b64encode(record).decode("ascii")
            params["encoding"] = "base64"
        self._write(
            {"jsonrpc": "2.0", "method": "run/transcript", "params": params}, from_worker=True
        )

    def stopping(self) -> bool:
        return self._stop.is_set()

    def wait(self, seconds: float) -> bool:
        return self._stop.wait(seconds)

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
                    raise _Exit(0)
                # _WORKER_DONE: the result is out (or the run failed); wait for shutdown.
        except _Exit as done:
            return done.code

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
                f"The Ollama runner doesn't know the method {method!r}.",
                "Use a method of the runner contract.",
            )

    def _initialize(self, id_: object, params: object) -> None:
        offered = params.get("protocolVersions") if isinstance(params, dict) else None
        if not isinstance(offered, list) or not any(v in p.PROTOCOL_VERSIONS for v in offered):
            self._error(
                id_,
                p.JSONRPC_REFUSED,
                "runner.unsupported-version",
                f"The Ollama runner supports protocol version(s) {list(p.PROTOCOL_VERSIONS)}, "
                f"none of which was offered ({offered!r}).",
                "Offer a protocol version this runner supports.",
                {"supportedVersions": list(p.PROTOCOL_VERSIONS)},
            )
            return
        self._initialized = True
        chosen = max(v for v in offered if v in p.PROTOCOL_VERSIONS)
        self._result(
            id_,
            {
                "protocolVersion": chosen,
                "runner": {"name": NAME, "version": __version__},
                "capabilities": [],
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
            client = Client(options.endpoint)
            engine_version, window = self._preflight(client, options)
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
        except _Refused as refused:
            self._error(
                id_, refused.rpc_code, refused.code, refused.problem, refused.fix, refused.details
            )
            return
        self._run_id = start.run_id
        self._client = client
        self._result(id_, {"runId": start.run_id})
        conversation = Conversation(
            start=start,
            options=options,
            window=window,
            engine_version=engine_version,
            client=client,
            sink=self,
        )
        self._worker = threading.Thread(target=self._converse, args=(conversation,), daemon=True)
        self._worker.start()

    def _preflight(self, client: Client, options: Options) -> tuple[str, int]:
        """Ollama's version and the run's window, once Ollama, its version and the model pass
        (design D4, D15, D16). Raises _Refused or OptionsError."""
        endpoint = options.endpoint
        unreachable_fix = (
            f"Start Ollama (ollama serve) so it listens at {endpoint}, or set options.endpoint to "
            "where it listens."
        )
        try:
            version = client.version(PREFLIGHT_TIMEOUT_SECONDS)
        except (UnreachableError, StoppedError) as error:
            raise _Refused(
                p.JSONRPC_REFUSED,
                "ollama.unreachable",
                f"Ollama didn't answer at {endpoint} within {PREFLIGHT_TIMEOUT_SECONDS:g}s: "
                f"{error}.",
                unreachable_fix,
                {"endpoint": endpoint},
            ) from error
        for requirement in load():
            unmet = check(requirement, version)
            if unmet is not None:
                unmet_details = {"requirement": requirement.name, "wanted": requirement.wanted}
                if unmet.found is not None:
                    unmet_details["found"] = unmet.found
                raise _Refused(
                    p.JSONRPC_REFUSED,
                    "runner.requirement-unmet",
                    f"{unmet.problem}: the Ollama runner needs {requirement.name} "
                    f"{requirement.wanted}. {requirement.why}",
                    f"Upgrade Ollama to {requirement.minimum} or later (https://ollama.com/download).",
                    unmet_details,
                )
        try:
            shown = client.show(options.model, PREFLIGHT_TIMEOUT_SECONDS)
        except (UnreachableError, StoppedError) as error:
            raise _Refused(
                p.JSONRPC_REFUSED,
                "ollama.unreachable",
                f"Ollama at {endpoint} didn't describe the model {options.model!r}: {error}.",
                unreachable_fix,
                {"endpoint": endpoint},
            ) from error
        if shown is None:
            raise _Refused(
                p.JSONRPC_REFUSED,
                "ollama.model-not-found",
                f"Ollama at {endpoint} has no model {options.model!r}.",
                f"Pull it with: ollama pull {options.model}",
                {"endpoint": endpoint, "model": options.model},
            )
        capabilities = shown.get("capabilities")
        if not isinstance(capabilities, list) or "tools" not in capabilities:
            details: dict[str, Any] = {"model": options.model}
            if isinstance(capabilities, list) and all(isinstance(c, str) for c in capabilities):
                details["capabilities"] = capabilities
                problem = (
                    f"Ollama says the model {options.model!r} can't call tools (it can: "
                    f"{', '.join(capabilities) or 'nothing listed'})."
                )
                fix = "Use a model that can call tools, such as qwen3.5:4b."
            else:
                problem = f"Ollama didn't say whether the model {options.model!r} can call tools."
                fix = "Upgrade Ollama, so it says what each model can do."
            raise _Refused(p.JSONRPC_REFUSED, "ollama.model-without-tools", problem, fix, details)
        maximum = model_maximum(shown)
        if options.context_length is not None:
            if maximum is not None and options.context_length > maximum:
                raise OptionsError(
                    "ollama.invalid-options",
                    "options.contextLength",
                    f"{options.context_length} is above the model's maximum context of {maximum} "
                    "tokens.",
                    f"Give contextLength {maximum} or less.",
                )
            return version, options.context_length
        window = DEFAULT_CONTEXT_LENGTH if maximum is None else min(DEFAULT_CONTEXT_LENGTH, maximum)
        return version, window

    # The run

    def _converse(self, conversation: Conversation) -> None:
        try:
            conversation.run()
        except Exception as error:  # the runner's own failure: reported, then exit 1
            self._failed = True
            self._diagnose("the conversation failed:\n" + traceback.format_exc())
            conversation.fail(f"The Ollama runner failed: {type(error).__name__}: {error}")
        finally:
            self._inbox.put((_WORKER_DONE, b""))

    # Ending

    def _halt(self) -> None:
        """Stop the run: nothing more from the worker, the request in flight closed, and the worker
        given a moment to finish."""
        with self._out:
            self._stop.set()
        if self._client is not None:
            self._client.close()
        if self._worker is not None:
            self._worker.join(STOP_GRACE_SECONDS)
            if self._worker.is_alive():
                self._diagnose(f"the conversation didn't stop within {STOP_GRACE_SECONDS:g}s")

    def _end(self, id_: object, why: str | None) -> NoReturn:
        """Answer run/cancel or shutdown, stop, and exit."""
        with self._out:
            self._stop.set()
        if why is not None:
            self._diagnose(why)
        self._result(id_, {})
        self._halt()
        raise _Exit(1 if self._failed else 0)


def main() -> NoReturn:
    code = Runner(sys.stdin.buffer, sys.stdout.buffer, sys.stderr.buffer).run()
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(OSError):
            stream.flush()
    # The reader thread may still be blocked on standard input, which would abort a normal exit
    # at interpreter shutdown; the scripted and Claude Code runners exit the same way.
    os._exit(code)
