"""Drive a mistralrs runner process as troupe does, over its standard input and output, with every
wait bounded (no test waits silently or for ever)."""

import json
import queue
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

PLUGIN = Path(__file__).resolve().parents[1]
CHECK_MODEL = PLUGIN / "src" / "troupe_runner_mistralrs" / "check_model" / "stories260K.gguf"
REAL = (sys.executable, "-m", "troupe_runner_mistralrs")
"""The runner with the real engine, mistral.rs."""
STAND_IN = (sys.executable, str(Path(__file__).with_name("stand_in_runner.py")))
"""The runner with the engine stand-in, which serves recorded responses."""

READ_TIMEOUT_SECONDS = 120.0
"""The longest a test waits for one line: generous, for a Mac's first Metal warm-up."""


class Session:
    """One runner process, its lines read on a thread so each wait can be bounded."""

    def __init__(self, command: Sequence[str], env: dict[str, str] | None = None) -> None:
        self.process = subprocess.Popen(
            list(command),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        self.lines: list[bytes] = []
        """Every line the runner wrote to standard output, as it wrote it."""
        self._queue: queue.Queue[bytes | None] = queue.Queue()
        self._stderr: list[bytes] = []
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read(self) -> None:
        assert self.process.stdout is not None
        for line in iter(self.process.stdout.readline, b""):
            self.lines.append(line)
            self._queue.put(line)
        self._queue.put(None)

    def _read_stderr(self) -> None:
        assert self.process.stderr is not None
        self._stderr.append(self.process.stderr.read())

    def stderr(self, timeout: float = 10.0) -> bytes:
        """Everything the runner wrote to standard error, once it has exited."""
        self.process.wait(timeout)
        deadline = time.monotonic() + timeout
        while not self._stderr and time.monotonic() < deadline:
            time.sleep(0.01)
        return b"".join(self._stderr)

    def send(self, message: dict[str, Any]) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(message).encode() + b"\n")
        self.process.stdin.flush()

    def close_input(self) -> None:
        assert self.process.stdin is not None
        self.process.stdin.close()

    def read(self, timeout: float = READ_TIMEOUT_SECONDS) -> dict[str, Any] | None:
        """The next message, or None at end of output. Fails the test after ``timeout``."""
        line = self._queue.get(timeout=timeout)
        return None if line is None else json.loads(line)

    def initialize(self) -> dict[str, Any]:
        self.send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersions": [0], "capabilities": ["transcript-kinds"]},
            }
        )
        answer = self.read()
        assert answer is not None
        return answer

    def start(self, params: dict[str, Any]) -> dict[str, Any]:
        self.send({"jsonrpc": "2.0", "id": 2, "method": "run/start", "params": params})
        answer = self.read()
        assert answer is not None
        return answer

    def until_result(self) -> list[dict[str, Any]]:
        """Every message up to and including the run's result event."""
        seen = []
        while True:
            message = self.read()
            assert message is not None, "the runner ended its output before its result"
            seen.append(message)
            params = message.get("params", {})
            if message.get("method") == "run/event" and params.get("type") == "result":
                return seen

    def shutdown(self, timeout: float = 30.0) -> int:
        self.send({"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": {}})
        return self.process.wait(timeout)

    def kill(self) -> None:
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait(10)


def run_start(
    workspace: Path,
    scratch: Path,
    model: str,
    *,
    direction: str = "Say hello.",
    options: dict[str, Any] | None = None,
    on_context_full: str = "fail",
    character: str | None = None,
    write: Sequence[str] = (),
) -> dict[str, Any]:
    """run/start's params for a run on the in-process runtime with ``model``."""
    params: dict[str, Any] = {
        "runId": str(uuid.uuid4()),
        "direction": direction,
        "workspace": str(workspace),
        "options": options if options is not None else {},
        "limits": {"eventMaxBytes": 65536},
        "effects": {"write": list(write), "delete": [], "move": []},
        "scratch": str(scratch),
        "onContextFull": on_context_full,
        "runtime": {"name": "mistralrs", "model": model, "credential": False},
    }
    if character is not None:
        params["character"] = character
    return params


def events(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [m["params"] for m in messages if m.get("method") == "run/event"]


def transcript(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [m["params"] for m in messages if m.get("method") == "run/transcript"]
