"""Drive the Claude Code runner over pipes, as troupe would, and check every message against the
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
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

SCHEMAS = Path(__file__).resolve().parents[3] / "protocol" / "schemas"
RUNNER_SCHEMAS = (
    Path(__file__).resolve().parents[1] / "src" / "troupe_runner_claude_code" / "schemas"
)
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "claude-code"
BASE = "https://troupe.run/protocol/runner/"
OWN = "https://troupe.run/plugins/runner-claude-code/"
RESULTS = {
    "initialize": "initialize.schema.json#/$defs/result",
    "run/start": "run-start.schema.json#/$defs/result",
    "run/cancel": "run-cancel.schema.json#/$defs/result",
    "shutdown": "shutdown.schema.json#/$defs/result",
}
TIMEOUT = 30.0
EVENT_MAX_BYTES = 65536


@cache
def _registry() -> Registry[Any]:
    paths = [
        SCHEMAS / "error.schema.json",
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


def own_validator(ref: str) -> jsonschema.Draft202012Validator:
    """A validator for this runner's own schema at ``ref``, such as options.schema.json."""
    return jsonschema.Draft202012Validator({"$ref": urljoin(OWN, ref)}, registry=_registry())


def validate(instance: object, ref: str) -> None:
    validator(ref).validate(instance)


def new_run_id() -> str:
    return str(uuid.uuid4())


def recording(name: str) -> list[dict[str, Any]]:
    """A fixture's recording: each line as ``{"transcript": ...}`` or ``{"event": ...}``."""
    text = (FIXTURES / name / "recording.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


class Session:
    """One Claude Code runner process. Every message either side sends is kept for validation."""

    def __init__(self, workspace: Path, env: Mapping[str, str]) -> None:
        self.workspace = workspace
        environment = dict(env)
        if sys.platform == "win32" and "SYSTEMROOT" in os.environ:
            environment.setdefault("SYSTEMROOT", os.environ["SYSTEMROOT"])
        self.process = subprocess.Popen(
            [sys.executable, "-m", "troupe_runner_claude_code"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=workspace,
            env=environment,
        )
        self.sent: list[dict[str, Any]] = []
        self.refused: set[int] = set()
        """Ids of requests the test sent invalid on purpose: the schema must refuse them too."""
        self.received: list[dict[str, Any]] = []
        self._lines: queue.Queue[bytes] = queue.Queue()
        self._next_id = 1
        self.run_id = new_run_id()
        self._stderr = b""
        threading.Thread(target=self._read, daemon=True).start()
        self._stderr_reader = threading.Thread(target=self._read_stderr, daemon=True)
        self._stderr_reader.start()

    def _read(self) -> None:
        assert self.process.stdout is not None
        for line in iter(self.process.stdout.readline, b""):
            self._lines.put(line)
        self._lines.put(b"")

    def _read_stderr(self) -> None:
        stream = self.process.stderr
        assert stream is not None
        while chunk := os.read(stream.fileno(), 65536):
            self._stderr += chunk

    def line(self, timeout: float = TIMEOUT) -> bytes:
        """The next raw line from the runner, or b"" at end of output."""
        return self._lines.get(timeout=timeout)

    def message(self, timeout: float = TIMEOUT) -> dict[str, Any]:
        line = self.line(timeout)
        assert line, "the runner ended its output"
        data: dict[str, Any] = json.loads(line)
        self.received.append(data)
        return data

    def rest(self, timeout: float = TIMEOUT) -> list[dict[str, Any]]:
        """Every message until the runner ends its output."""
        messages = []
        while line := self.line(timeout):
            data: dict[str, Any] = json.loads(line)
            self.received.append(data)
            messages.append(data)
        return messages

    def send(self, method: str, params: dict[str, Any]) -> int:
        id_ = self._next_id
        self._next_id += 1
        message = {"jsonrpc": "2.0", "id": id_, "method": method, "params": params}
        self.sent.append(message)
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(message).encode() + b"\n")
        self.process.stdin.flush()
        return id_

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Send a request and return its response, keeping notifications that arrive first."""
        id_ = self.send(method, params)
        while True:
            message = self.message()
            if message.get("id") == id_:
                return message

    def initialize(self, versions: list[int] | None = None) -> dict[str, Any]:
        return self.request(
            "initialize",
            {
                "protocolVersions": [0] if versions is None else versions,
                "host": {"name": "test", "version": "1"},
                "capabilities": [],
            },
        )

    def start(
        self,
        options: dict[str, Any] | None = None,
        *,
        valid: bool = True,
        direction: str = "say hi",
        character: str | None = None,
        event_max_bytes: int = EVENT_MAX_BYTES,
    ) -> dict[str, Any]:
        """Initialize, then send run/start. ``valid=False`` marks options the runner must refuse,
        which the runner's options schema must refuse as well."""
        self.initialize()
        if not valid:
            self.refused.add(self._next_id)
        params: dict[str, Any] = {
            "runId": self.run_id,
            "direction": direction,
            "workspace": str(self.workspace),
            "options": {} if options is None else options,
            "limits": {"eventMaxBytes": event_max_bytes},
        }
        if character is not None:
            params["character"] = character
        return self.request("run/start", params)

    def close_stdin(self) -> None:
        assert self.process.stdin is not None
        self.process.stdin.close()

    def wait(self, timeout: float = TIMEOUT) -> int:
        return self.process.wait(timeout=timeout)

    def stderr(self) -> bytes:
        """What the runner wrote to standard error, once it has exited."""
        self.wait()
        self._stderr_reader.join(TIMEOUT)
        return self._stderr

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
