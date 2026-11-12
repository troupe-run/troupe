"""Shared helpers for the LM Studio runner's tests: the schemas, the test limits, and (with
fake_lm_studio) driving the runner as troupe would.

Self-contained: no troupe imports. The contract's schemas are read from protocol/ at the repository
root, and the runner's own from its package's schemas/ directory, so messages are validated with the
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
from typing import Any, Final
from urllib.parse import urljoin

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

ROOT = Path(__file__).resolve().parents[3]
SCHEMAS = ROOT / "protocol" / "schemas"
PACKAGE = Path(__file__).resolve().parents[1] / "src" / "troupe_runner_lm_studio"
RUNNER_SCHEMAS = PACKAGE / "schemas"
BASE = "https://troupe.run/protocol/runner/"
OWN = "https://troupe.run/plugins/runner-lm-studio/"
RESULTS = {
    "initialize": "initialize.schema.json#/$defs/result",
    "run/start": "run-start.schema.json#/$defs/result",
    "run/cancel": "run-cancel.schema.json#/$defs/result",
    "shutdown": "shutdown.schema.json#/$defs/result",
}
TIMEOUT = 30.0
EVENT_MAX_BYTES = 65536
MODEL = "google/gemma-4-e4b"

TEST_LIMITS: Final[dict[str, int]] = {"maxTurns": 4, "maxTotalTokens": 20_000}
"""The limits every run a test starts uses, unless the test sets its own: low, so a runaway loop
stops within a few rounds. The runner's defaults are for real work, and are checked by parsing
options, never by running on them."""


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
    """A validator for the contract's schema at ``ref``, bound to this runner's schemas."""
    return jsonschema.Draft202012Validator(bound(ref), registry=_registry())


def own_validator(ref: str) -> jsonschema.Draft202012Validator:
    """A validator for this runner's own schema at ``ref``, such as options.schema.json."""
    return jsonschema.Draft202012Validator({"$ref": urljoin(OWN, ref)}, registry=_registry())


def validate(instance: object, ref: str) -> None:
    validator(ref).validate(instance)


class Session:
    """One LM Studio runner process. Every message either side sends is kept for validation."""

    def __init__(
        self,
        workspace: Path,
        env: Mapping[str, str] | None = None,
        capabilities: list[str] | None = None,
    ) -> None:
        self.workspace = workspace
        self.capabilities = ["transcript-kinds"] if capabilities is None else capabilities
        environment = dict(env or {})
        if sys.platform == "win32" and "SYSTEMROOT" in os.environ:
            environment.setdefault("SYSTEMROOT", os.environ["SYSTEMROOT"])
        self.process = subprocess.Popen(
            [sys.executable, "-m", "troupe_runner_lm_studio"],
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
        self.run_id = str(uuid.uuid4())
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

    def message(self, timeout: float = TIMEOUT) -> dict[str, Any]:
        line = self._lines.get(timeout=timeout)
        assert line, "the runner ended its output"
        data: dict[str, Any] = json.loads(line)
        self.received.append(data)
        return data

    def rest(self, timeout: float = TIMEOUT) -> list[dict[str, Any]]:
        """Every message until the runner ends its output."""
        messages = []
        while line := self._lines.get(timeout=timeout):
            data: dict[str, Any] = json.loads(line)
            self.received.append(data)
            messages.append(data)
        return messages

    def until_result(self, timeout: float = TIMEOUT) -> list[dict[str, Any]]:
        """Every message up to and including the run's result event."""
        messages = []
        while True:
            message = self.message(timeout)
            messages.append(message)
            params = message.get("params", {})
            if message.get("method") == "run/event" and params.get("type") == "result":
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

    def initialize(self) -> dict[str, Any]:
        return self.request(
            "initialize",
            {
                "protocolVersions": [0],
                "host": {"name": "test", "version": "1"},
                "capabilities": self.capabilities,
            },
        )

    def start(
        self,
        endpoint: str | None,
        options: dict[str, Any] | None = None,
        *,
        model: str = MODEL,
        credential: bool = False,
        price: dict[str, float] | None = None,
        valid: bool = True,
        direction: str = "Do the task.",
        character: str | None = None,
        event_max_bytes: int = EVENT_MAX_BYTES,
        effects: dict[str, list[str]] | None = None,
        on_context_full: str = "fail",
    ) -> dict[str, Any]:
        """Initialize, then send run/start with a runtime naming ``endpoint`` (None: no runtime).
        ``options`` default to TEST_LIMITS. ``valid=False`` marks a run/start the runner must
        refuse, which the contract's schema must refuse as well."""
        options = dict(TEST_LIMITS) if options is None else options
        self.initialize()
        if not valid:
            self.refused.add(self._next_id)
        params: dict[str, Any] = {
            "runId": self.run_id,
            "direction": direction,
            "workspace": str(self.workspace),
            "options": options,
            "limits": {"eventMaxBytes": event_max_bytes},
            "effects": {"write": [], "delete": [], "move": [], **(effects or {})},
            "scratch": str(self.scratch()),
            "onContextFull": on_context_full,
        }
        if endpoint is not None:
            params["runtime"] = {
                "name": "lm-studio",
                "endpoint": endpoint,
                "model": model,
                "credential": credential,
            }
            if price is not None:
                params["runtime"]["price"] = price
        if character is not None:
            params["character"] = character
        return self.request("run/start", params)

    def scratch(self) -> Path:
        """The run's scratch directory: beside the workspace, made when first asked for."""
        scratch = self.workspace.parent / f"{self.workspace.name}-scratch"
        scratch.mkdir(exist_ok=True)
        return scratch

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

    def shutdown(self) -> int:
        """Send shutdown after the result; the exit code."""
        self.request("shutdown", {})
        return self.wait()

    def kill(self) -> None:
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=TIMEOUT)


def events(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The run events among ``messages``, in order."""
    return [m["params"] for m in messages if m.get("method") == "run/event"]


def transcript(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The transcript records among ``messages``, in order."""
    return [m["params"] for m in messages if m.get("method") == "run/transcript"]


def result(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """The run's result event."""
    found = [e for e in events(messages) if e["type"] == "result"]
    assert len(found) == 1, found
    return found[0]
