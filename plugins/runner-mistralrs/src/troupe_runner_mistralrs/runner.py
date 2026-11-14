"""The mistralrs runner's process: the runner contract over standard input and output
(in-process-runner design D1 to D4).

The entry point first keeps standard output for troupe's messages and points file descriptor 1 at
standard error, before anything imports ``mistralrs``, since the engine writes its log lines to
file descriptor 1 (design D3).

The main thread reads troupe's messages and answers them. Before it answers run/start, it checks
what can be checked quickly: the params, the options, the run's in-process runtime and its model
file, the installed engine's version, and on macOS that the engine can compile its Metal kernels
under this Python (design D4). After it answers, a worker thread loads the model and runs the
conversation.

Both threads write to the protocol channel one whole line at a time, under one lock. Stopping (on
run/cancel, end of input or shutdown) sets a flag under that same lock before the answer is
written, so nothing the worker sends can follow it. The engine's work can't be interrupted, so the
runner then exits, abandoning any call in flight (design D2).
"""

import base64
import contextlib
import json
import os
import platform
import queue
import sys
import threading
import traceback
from collections.abc import Callable
from typing import Any, BinaryIO, NoReturn

from troupe_plugin_sdk import runner as p
from troupe_runner_mistralrs import NAME, __version__
from troupe_runner_mistralrs.conversation import Conversation
from troupe_runner_mistralrs.defaults import DEFAULT_CONTEXT_LENGTH, STOP_GRACE_SECONDS
from troupe_runner_mistralrs.options import OptionsError, parse_options
from troupe_runner_mistralrs.port import EngineFailure, Loader, LoadSpec, PlatformCheck
from troupe_runner_mistralrs.requirements import installed, load, unmet
from troupe_runner_mistralrs.runtime import RuntimeRefusedError, from_run_start

_TROUPE = "troupe"
_TROUPE_EOF = "troupe-eof"
_WORKER_DONE = "worker-done"

MANAGED_PYTHON_FIX = (
    "Install troupe on a uv-managed Python, whose build mistral.rs's Metal kernels compile under: "
    'uv tool install --managed-python --no-sources "troupe-run[mistralrs] @ git+https://github.com/'
    'troupe-run/troupe@<tag>#subdirectory=packages/troupe-run". The install page says which tag.'
)
"""The fix for a macOS Python mistral.rs can't compile its Metal kernels under (design D4)."""


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


def is_metal() -> bool:
    """Whether the engine runs on Metal here: macOS, where it takes a KV budget (design D7)."""
    return sys.platform == "darwin"


class Runner:
    def __init__(
        self,
        stdin: BinaryIO,
        stdout: BinaryIO,
        stderr: BinaryIO,
        *,
        loader: Loader,
        check: PlatformCheck,
        versions: Callable[[str], str | None] = installed,
    ) -> None:
        self._stdin = stdin
        self._stdout = stdout
        self._stderr = stderr
        self._loader = loader
        self._check = check
        self._versions = versions
        self._inbox: queue.Queue[tuple[str, bytes]] = queue.Queue()
        self._out = threading.Lock()
        self._stop = threading.Event()
        self._kinds = False
        """Whether troupe offered transcript-kinds, which this runner then accepts."""
        self._initialized = False
        self._run_id: str | None = None
        self._worker: threading.Thread | None = None
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
        self._stderr.write(f"mistralrs runner: {text}\n".encode())
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

    def transcript(self, kind: p.TranscriptKind, record: bytes) -> None:
        params: dict[str, Any] = {"runId": self._run_id}
        if self._kinds:
            params["kind"] = kind
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
            # The runner's own bug on the main thread: say so, stop the worker, and exit 1
            # through main's os._exit.
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
                f"The mistralrs runner doesn't know the method {method!r}.",
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
                f"The mistralrs runner supports protocol version(s) {list(p.PROTOCOL_VERSIONS)}, "
                f"none of which was offered ({offered!r}).",
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

    # run/start (design D4)

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
            runtime = from_run_start(start)
            engine_version = self._requirements()
            self._platform()
        except (OptionsError, RuntimeRefusedError) as error:
            details = error.details if isinstance(error, RuntimeRefusedError) else None
            self._error(
                id_,
                p.JSONRPC_INVALID_PARAMS,
                error.code,
                f"{error.where}: {error.problem}",
                error.fix,
                details if details is not None else {"where": error.where},
            )
            return
        except _Refused as refused:
            self._error(
                id_, refused.rpc_code, refused.code, refused.problem, refused.fix, refused.details
            )
            return
        try:
            # Made before run/start is answered: it checks the workspace, scratch directory and
            # declaration, and a run it can't make is refused, never acknowledged and then dropped.
            conversation = Conversation(
                start=start,
                options=options,
                model=str(runtime.model),
                spec=LoadSpec(model=runtime.model, seed=options.seed),
                engine_version=engine_version,
                loader=self._windowed_loader(options.context_length),
                sink=self,
            )
        except (OSError, ValueError) as error:
            self._error(
                id_,
                p.JSONRPC_INVALID_PARAMS,
                "runner.invalid-params",
                f"The run's workspace or scratch directory can't be used: {error}",
                "Send a workspace that exists, and a scratch directory that exists outside it.",
            )
            return
        self._run_id = start.run_id
        self._result(id_, {"runId": start.run_id})
        self._worker = threading.Thread(target=self._converse, args=(conversation,), daemon=True)
        self._worker.start()

    def _windowed_loader(self, context_length: int | None) -> Loader:
        """The loader, giving the engine the run's window as its KV budget on Metal (design D7).
        The window is the options' when they set one; otherwise the runner's default, which the
        conversation lowers to the model's length once it's loaded."""

        def load(spec: LoadSpec) -> Any:  # noqa: ANN401 - an Engine
            if is_metal():
                window = context_length if context_length is not None else DEFAULT_CONTEXT_LENGTH
                spec = LoadSpec(model=spec.model, seed=spec.seed, kv_tokens=window)
            return self._loader(spec)

        return load

    def _requirements(self) -> str:
        """The installed engine's version, once it's the version the runner was built for (design
        D9). Raises _Refused."""
        requirements = load()
        found = {requirement.name: self._versions(requirement.name) for requirement in requirements}
        problem = unmet(requirements, found)
        if problem is not None:
            requirement = problem.requirement
            details = {"requirement": requirement.name, "wanted": requirement.version}
            if problem.found is not None:
                details["found"] = problem.found
            have = problem.found if problem.found is not None else "nothing"
            raise _Refused(
                p.JSONRPC_REFUSED,
                "runner.requirement-unmet",
                f"The mistralrs runner needs {requirement.name} {requirement.version}, and "
                f"{have} is installed. {requirement.why}",
                f"Reinstall troupe-run[mistralrs], which pins {requirement.name} "
                f"{requirement.version}.",
                details,
            )
        version = found[requirements[0].name]
        if version is None:  # pragma: no cover - unmet would have said so
            raise RuntimeError("the engine's version is unknown")
        return version

    def _platform(self) -> None:
        """On macOS, refuse a Python the engine can't compile its Metal kernels under (design D4).
        Raises _Refused."""
        try:
            self._check()
        except EngineFailure as failure:
            if failure.kind == "metal":
                raise _Refused(
                    p.JSONRPC_REFUSED,
                    "mistralrs.unsupported-python",
                    f"mistral.rs can't compile its Metal kernels under this Python "
                    f"({sys.executable}, {platform.python_version()}): which Pythons work depends "
                    "on the macOS SDK each was built with, and Homebrew's on macOS 27 and "
                    f"python.org's 3.12 don't. The engine said: {failure.message}",
                    MANAGED_PYTHON_FIX,
                    {"python": sys.executable, "version": platform.python_version()},
                ) from None
            raise _Refused(
                p.JSONRPC_REFUSED,
                "runner.requirement-unmet",
                f"mistral.rs couldn't load the check model the runner carries, so it can't run "
                f"here: {failure.message}",
                "Report it, with this message, at https://github.com/troupe-run/troupe/issues.",
                {
                    "requirement": "mistral.rs on this platform",
                    "wanted": "the check model loads",
                    "found": failure.message,
                },
            ) from None

    # The run

    def _converse(self, conversation: Conversation) -> None:
        try:
            conversation.run()
        except Exception as error:  # the runner's own failure: reported, then exit 1
            self._failed = True
            self._diagnose("the conversation failed:\n" + traceback.format_exc())
            conversation.fail(f"The mistralrs runner failed: {type(error).__name__}: {error}")
        finally:
            self._inbox.put((_WORKER_DONE, b""))

    # Ending (design D2)

    def _halt(self) -> None:
        """Stop the run: nothing more from the worker, and the worker given a moment to reach a
        point where it isn't writing. An engine call in flight is abandoned: main exits the
        process."""
        with self._out:
            self._stop.set()
        if self._worker is not None:
            self._worker.join(STOP_GRACE_SECONDS)
            if self._worker.is_alive():
                self._diagnose(
                    f"the engine's call didn't end within {STOP_GRACE_SECONDS:g}s; exiting "
                    "without it"
                )

    def _end(self, id_: object, why: str | None) -> NoReturn:
        """Answer run/cancel or shutdown, stop, and exit."""
        with self._out:
            self._stop.set()
        if why is not None:
            self._diagnose(why)
        self._result(id_, {})
        self._halt()
        raise _Exit(1 if self._failed else 0)


def keep_protocol_channel() -> BinaryIO:
    """Keep standard output for troupe's messages, and point file descriptor 1 at standard error,
    so whatever the engine (or a stray print) writes to it never reaches the protocol channel
    (design D3). On Windows the C runtime's dup2 on descriptor 1 also moves the standard handle
    the engine writes through. Call it before anything imports ``mistralrs``."""
    sys.stdout.flush()
    protocol = os.fdopen(os.dup(1), "wb", buffering=0)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    return protocol


def main(loader: Loader | None = None, check: PlatformCheck | None = None) -> NoReturn:
    """Serve one run. ``loader`` and ``check`` are the engine's: the real one, mistral.rs, unless
    a test passes a stand-in."""
    protocol = keep_protocol_channel()
    if loader is None or check is None:
        from troupe_runner_mistralrs import engine

        loader = loader if loader is not None else engine.load
        check = check if check is not None else engine.check_platform
    code = Runner(sys.stdin.buffer, protocol, sys.stderr.buffer, loader=loader, check=check).run()
    for stream in (protocol, sys.stderr):
        with contextlib.suppress(OSError):
            stream.flush()
    # The reader thread may be blocked on standard input, and the engine may be mid-call on the
    # worker, neither of which can be stopped: leave without them (design D2).
    os._exit(code)
