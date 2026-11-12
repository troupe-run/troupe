"""Drive the scripted runner over pipes, as troupe would, and check every message against the
schemas.

Self-contained: no troupe imports. The contract's schemas are read from protocol/ at the repository
root, and the runner's own from its package's schemas/ directory. Messages are validated with the
runner's schemas filling the contract's extension points, as troupe would see them.
"""

import json
import os
import queue
import subprocess
import sys
import threading
import uuid
from functools import cache
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

SCHEMAS = Path(__file__).resolve().parents[3] / "protocol" / "schemas"
RUNNER_SCHEMAS = Path(__file__).resolve().parents[1] / "src" / "troupe_runner_scripted" / "schemas"
BASE = "https://troupe.run/protocol/runner/"
OWN = "https://troupe.run/plugins/runner-scripted/"
RESULTS = {
    "initialize": "initialize.schema.json#/$defs/result",
    "run/start": "run-start.schema.json#/$defs/result",
    "run/cancel": "run-cancel.schema.json#/$defs/result",
    "shutdown": "shutdown.schema.json#/$defs/result",
}
TIMEOUT = 30.0


@cache
def _registry() -> Registry[Any]:
    paths = [
        SCHEMAS / "error.schema.json",
        SCHEMAS / "effects.schema.json",
        SCHEMAS / "runtime.schema.json",
        *sorted((SCHEMAS / "runner").glob("*.schema.json")),
        *sorted(RUNNER_SCHEMAS.glob("*.schema.json")),
    ]
    schemas = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    return Registry().with_resources(
        (s["$id"], Resource.from_contents(s, default_specification=DRAFT202012)) for s in schemas
    )


def bound(ref: str) -> dict[str, Any]:
    """The contract's schema at ``ref``, with this runner's schemas filling its extension points."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": urljoin(OWN, "bound.schema.json"),
        "$ref": urljoin(BASE, ref),
        "$defs": {
            "options": {
                "$dynamicAnchor": "runnerOptions",
                "$ref": urljoin(OWN, "options.schema.json"),
            },
            "errors": {
                "$dynamicAnchor": "runnerErrors",
                "$ref": urljoin(OWN, "errors.schema.json"),
            },
        },
    }


def validator(ref: str) -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(bound(ref), registry=_registry())


def validate(instance: object, ref: str) -> None:
    validator(ref).validate(instance)


def new_run_id() -> str:
    return str(uuid.uuid4())


class Session:
    """One scripted runner process. Every message either side sends is kept for validation."""

    def __init__(
        self, workspace: Path, env: dict[str, str] | None = None, args: list[str] | None = None
    ) -> None:
        """``env``: variables added to the runner's environment, such as a run's credential.
        ``args``: the runner's command-line arguments, such as ``--transcript-kinds``."""
        self.workspace = workspace
        environment = {
            k: v for k, v in os.environ.items() if k.upper() != "TROUPE_RUNTIME_CREDENTIAL"
        }
        self.process = subprocess.Popen(
            [sys.executable, "-m", "troupe_runner_scripted", *(args or [])],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=workspace,
            env={**environment, **(env or {})},
        )
        self.sent: list[dict[str, Any]] = []
        self.refused: set[int] = set()
        """Ids of requests the test sent invalid on purpose: the schema must refuse them too."""
        self.received: list[dict[str, Any]] = []
        self.raw_lines: list[bytes] = []
        """Every line the runner wrote, as it wrote it, whether or not a test has read it yet."""
        self._lines: queue.Queue[bytes] = queue.Queue()
        self._passed: list[dict[str, Any]] = []
        """Messages request() read past while waiting for its answer, which until_result() takes
        first (request-keeps-notifications design D1)."""
        self._next_id = 1
        self.run_id = new_run_id()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        assert self.process.stdout is not None
        for line in iter(self.process.stdout.readline, b""):
            self.raw_lines.append(line)
            self._lines.put(line)
        self._lines.put(b"")

    def line(self, timeout: float = TIMEOUT) -> bytes:
        """The next raw line from the runner, or b"" at end of output."""
        return self._lines.get(timeout=timeout)

    def message(self, timeout: float = TIMEOUT) -> dict[str, Any]:
        line = self.line(timeout)
        assert line, "the runner ended its output"
        data: dict[str, Any] = json.loads(line)
        self.received.append(data)
        return data

    def send(self, method: str, params: dict[str, Any]) -> int:
        id_ = self._next_id
        self._next_id += 1
        message = {"jsonrpc": "2.0", "id": id_, "method": method, "params": params}
        self.sent.append(message)
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(message).encode() + b"\n")
        self.process.stdin.flush()
        return id_

    def send_raw(self, data: bytes) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(data)
        self.process.stdin.flush()

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Send a request and return its response. Messages that arrive first are kept in
        ``received``, and set aside for until_result(); message() and notifications() read only
        what follows the response."""
        id_ = self.send(method, params)
        while True:
            message = self.message()
            if message.get("id") == id_:
                return message
            self._passed.append(message)

    def scratch(self) -> Path:
        """The run's scratch directory: beside the workspace, made when first asked for."""
        scratch = self.workspace.parent / f"{self.workspace.name}-scratch"
        scratch.mkdir(exist_ok=True)
        return scratch

    def initialize(self, capabilities: list[str] | None = None) -> dict[str, Any]:
        """The handshake, offering ``capabilities`` (none unless given)."""
        offer = {"name": "test", "version": "1"}
        return self.request(
            "initialize",
            {"protocolVersions": [0], "host": offer, "capabilities": capabilities or []},
        )

    def start(
        self,
        options: dict[str, Any],
        *,
        valid: bool = True,
        character: str | None = None,
        effects: dict[str, list[str]] | None = None,
        runtime: dict[str, Any] | None = None,
        on_context_full: str = "fail",
    ) -> dict[str, Any]:
        """Initialize, then send run/start with ``options`` (and ``character``, when given).
        ``valid=False`` marks options the runner must refuse, which the runner's options schema
        must refuse as well."""
        self.initialize()
        if not valid:
            self.refused.add(self._next_id)
        params: dict[str, Any] = {
            "runId": self.run_id,
            "direction": "test",
            "workspace": str(self.workspace),
            "options": options,
            "limits": {"eventMaxBytes": 65536},
            "effects": {"write": [], "delete": [], "move": [], **(effects or {})},
            "scratch": str(self.scratch()),
            "onContextFull": on_context_full,
        }
        if character is not None:
            params["character"] = character
        if runtime is not None:
            params["runtime"] = runtime
        return self.request("run/start", params)

    def play(
        self,
        script: dict[str, Any],
        *,
        valid: bool = True,
        character: str | None = None,
        effects: dict[str, list[str]] | None = None,
        runtime: dict[str, Any] | None = None,
        on_context_full: str = "fail",
    ) -> dict[str, Any]:
        return self.start(
            {"script": script},
            valid=valid,
            character=character,
            effects=effects,
            runtime=runtime,
            on_context_full=on_context_full,
        )

    def notifications(self, count: int) -> list[dict[str, Any]]:
        return [self.message() for _ in range(count)]

    def until_result(self, timeout: float = TIMEOUT) -> list[dict[str, Any]]:
        """Every message up to and including the run's result event: first those a request()
        read past, then the stream. A result that came before a request's answer is found, not
        waited for (#392). Raises queue.Empty if no result comes within ``timeout``."""
        messages = []
        while True:
            message = self._passed.pop(0) if self._passed else self.message(timeout)
            messages.append(message)
            params = message.get("params", {})
            if message.get("method") == "run/event" and params.get("type") == "result":
                return messages

    def close_stdin(self) -> None:
        assert self.process.stdin is not None
        self.process.stdin.close()

    def wait(self, timeout: float = TIMEOUT) -> int:
        return self.process.wait(timeout=timeout)

    def stderr(self) -> bytes:
        assert self.process.stderr is not None
        return self.process.stderr.read()

    def validate_all(self) -> None:
        """Every message either side sent is valid, and each result matches its method."""
        methods: dict[object, str] = {}
        for message in self.sent:
            if message["id"] in self.refused:
                assert not validator("message.schema.json#/$defs/fromHost").is_valid(message)
            else:
                validate(message, "message.schema.json#/$defs/fromHost")
            methods[message["id"]] = message["method"]
        for message in self.received:
            validate(message, "message.schema.json#/$defs/fromRunner")
            if "result" in message:
                validate(message["result"], RESULTS[methods[message["id"]]])

    def kill(self) -> None:
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=TIMEOUT)
