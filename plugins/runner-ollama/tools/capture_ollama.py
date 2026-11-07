"""Capture a fixture from a real Ollama, on this machine (local-model-runner design D12; spec:
ollama-runner, "Fixtures pair real Ollama output with protocol events").

    uv run python plugins/runner-ollama/tools/capture_ollama.py <scenario> [--endpoint URL]
    uv run python plugins/runner-ollama/tools/capture_ollama.py --list

Each scenario is fixed here (model, direction, options, effects and the files the workspace starts
with), so a capture can be repeated. The tool runs the runner's own conversation in a temporary
workspace, against Ollama, through a client that records what Ollama sends, and writes
fixtures/ollama/<scenario>/:

- ``preflight.json``: what Ollama answered to /api/version and /api/show;
- ``answers.json``: each /api/chat answer, its status and its lines (or its error body), which the
  fake Ollama replays;
- ``transcript.jsonl`` and ``events.json``: the transcript records and run events the runner sent,
  for the replay test to compare with. Review the events before committing: they're what the runner
  did, recorded, not what it should do;
- ``provenance.json``: Ollama's version, the model, the date, the command and the scrubbing.

It needs no credential. It refuses an endpoint that isn't on this machine, so it can't record
someone else's server by mistake. The workspace's and scratch directory's paths are replaced with
``<workspace>`` and ``<scratch>``, so no host path is committed.
"""

import argparse
import datetime
import json
import sys
import tempfile
import uuid
from collections.abc import Generator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from troupe_plugin_sdk import runner as p
from troupe_runner_ollama.client import Client, EngineError, RetryableError
from troupe_runner_ollama.conversation import Conversation
from troupe_runner_ollama.defaults import PREFLIGHT_TIMEOUT_SECONDS
from troupe_runner_ollama.options import parse_options
from troupe_runner_ollama.runner import default_window, model_maximum
from troupe_runner_ollama.runtime import checked

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ollama"
LOOPBACK = ("127.0.0.1", "::1", "localhost")
LOCAL_OLLAMA = "http://127.0.0.1:11434"
"""Where the tool looks for Ollama without --endpoint: Ollama's own default address, as troupe's
built-in ollama runtime has it. The runner itself holds no endpoint (ollama-uses-runtime D2)."""
EVENT_MAX_BYTES = 65536


@dataclass(frozen=True)
class Scenario:
    """One fixture's run."""

    what: str
    model: str
    """The runtime's model."""
    options: dict[str, Any]
    direction: str = ""
    effects: dict[str, list[str]] = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)
    preflight_only: bool = False
    """Only ask Ollama for its version and the model: the fixture is the preflight's answers."""
    note: str = ""


SCENARIOS: dict[str, Scenario] = {
    "success-with-tools": Scenario(
        "A Write the effects allow, then a final answer.",
        "qwen3:0.6b",
        {"think": False, "temperature": 0, "seed": 1},
        "Create the file out/hello.txt containing exactly: hello",
        {"write": ["out/**"]},
    ),
    "refused-by-effects": Scenario(
        "A Write outside the declared effects, refused by the SDK, then the model's answer.",
        "qwen3:0.6b",
        {"think": False, "temperature": 0, "seed": 1, "maxTurns": 3},
        "Create the file src/hello.txt containing exactly: hello",
        {"write": ["out/**"]},
    ),
    "thinking": Scenario(
        "A thinking model's answer, with no tool call: its thinking stays in the transcript.",
        "qwen3:0.6b",
        {"think": True, "temperature": 0, "seed": 1},
        "What is 2 + 2? Answer with only the number, and use no tools.",
    ),
    "context-overflow": Scenario(
        "A window too small for the conversation: with truncate false, Ollama refuses the "
        "request with status 400 instead of cutting it.",
        "qwen3:0.6b",
        {"think": False, "contextLength": 512},
        "Read notes.txt and summarise it.",
        files={"notes.txt": "A line of notes.\n" * 200},
    ),
    "model-not-found": Scenario(
        "/api/show's answer for a model that isn't pulled.",
        "troupe-capture-no-such-model",
        {},
        preflight_only=True,
    ),
    "no-tools-capability": Scenario(
        "/api/show's answer for a model whose template has no tools.",
        "troupe-capture-notools",
        {},
        preflight_only=True,
        note="Made for the capture with `ollama create troupe-capture-notools` from qwen3:0.6b "
        'with TEMPLATE "{{ .Prompt }}", and removed with `ollama rm` afterwards. Ollama 0.40.14 '
        "still lists tools for it (a qwen3-family model's capabilities come from its renderer), "
        'so set capabilities to ["completion"] by hand in preflight.json, and say so here.',
    ),
}


class RecordingClient(Client):
    """The runner's client, keeping each /api/chat answer as Ollama sent it."""

    def __init__(self, endpoint: str) -> None:
        super().__init__(endpoint)
        self.answers: list[dict[str, Any]] = []

    def chat(self, body: bytes) -> Generator[bytes]:
        lines: list[str] = []
        answer: dict[str, Any] = {"status": 200, "lines": lines}
        self.answers.append(answer)
        try:
            for line in super().chat(body):
                lines.append(line.decode("utf-8"))
                yield line
        except EngineError as error:
            answer.update(status=error.status, body=error.body.decode("utf-8"))
            del answer["lines"]
            raise
        except RetryableError as error:
            answer["failed"] = {"reason": error.reason, "message": error.message}
            raise


@dataclass
class _Sink:
    events: list[p.RunEvent] = field(default_factory=list)
    records: list[bytes] = field(default_factory=list)

    def event(self, event: p.RunEvent) -> None:
        self.events.append(event)

    def transcript(self, record: bytes) -> None:
        self.records.append(record)

    def stopping(self) -> bool:
        return False

    def wait(self, seconds: float) -> bool:
        return False


def scrub(text: str, paths: dict[str, str]) -> str:
    """``text`` with each host path replaced by its placeholder, in JSON-escaped form too."""
    for path, placeholder in paths.items():
        text = text.replace(json.dumps(path)[1:-1], placeholder).replace(path, placeholder)
    return text


def _write(directory: Path, name: str, value: object) -> None:
    (directory / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", "utf-8")


def capture(name: str, endpoint: str, out: Path = FIXTURES) -> Path:
    """Capture scenario ``name`` from Ollama at ``endpoint`` into ``out``/``name``."""
    host = urlsplit(endpoint).hostname
    if host not in LOOPBACK:
        raise SystemExit(
            f"capture_ollama: {endpoint} isn't on this machine; captures only record a local "
            "Ollama (127.0.0.1, ::1 or localhost)."
        )
    scenario = SCENARIOS[name]
    options = parse_options(scenario.options)
    runtime = p.RunStartRuntime(
        name="ollama", endpoint=endpoint, model=scenario.model, credential=False
    )
    model = scenario.model
    client = RecordingClient(checked(runtime).endpoint)
    version = client.version(PREFLIGHT_TIMEOUT_SECONDS)
    shown = client.show(model, PREFLIGHT_TIMEOUT_SECONDS)
    if shown is not None:
        for bulky in ("license", "modelfile", "template", "template_source"):
            shown.pop(bulky, None)
    directory = out / name
    directory.mkdir(parents=True, exist_ok=True)
    _write(directory, "preflight.json", {"model": model, "version": version, "show": shown})
    provenance: dict[str, Any] = {
        "what": scenario.what,
        "ollamaVersion": version,
        "model": model,
        "date": datetime.date.today().isoformat(),
        "command": ["capture_ollama.py", name],
        "options": scenario.options,
        "direction": scenario.direction,
        "effects": scenario.effects,
        "credential": "none: Ollama needs none",
        "scrubbing": "the workspace's and scratch directory's paths are <workspace> and "
        "<scratch>; /api/show's license, modelfile and template text are left out",
        "events": "recorded at capture, then reviewed by hand",
    }
    if scenario.note:
        provenance["note"] = scenario.note
    if scenario.preflight_only:
        _write(directory, "provenance.json", provenance)
        return directory
    with tempfile.TemporaryDirectory() as temporary:
        workspace = Path(temporary) / "workspace"
        scratch = Path(temporary) / "workspace-scratch"
        workspace.mkdir()
        scratch.mkdir()
        for relative, content in scenario.files.items():
            (workspace / relative).write_text(content, encoding="utf-8")
        start = p.RunStartParams(
            run_id=str(uuid.uuid4()),
            direction=scenario.direction,
            workspace=str(workspace),
            options={},
            limits=p.StartLimits(event_max_bytes=EVENT_MAX_BYTES),
            effects=p.EffectsDeclaration(
                write=scenario.effects.get("write", []),
                delete=scenario.effects.get("delete", []),
                move=scenario.effects.get("move", []),
            ),
            scratch=str(scratch),
            runtime=runtime,
        )
        maximum = model_maximum(shown or {})
        window = options.context_length or default_window(maximum)
        sink = _Sink()
        Conversation(
            start=start,
            options=options,
            model=model,
            window=window,
            engine_version=version,
            client=client,
            sink=sink,
        ).run()
        paths = {str(scratch): "<scratch>", str(workspace): "<workspace>"}
        records = [scrub(record.decode("utf-8"), paths) for record in sink.records]
        events = []
        for event in sink.events:
            data = event.to_data()
            data.pop("runId")
            data.pop("durationMs", None)
            events.append(json.loads(scrub(json.dumps(data, ensure_ascii=False), paths)))
        answers = json.loads(scrub(json.dumps(client.answers, ensure_ascii=False), paths))
    _write(directory, "answers.json", answers)
    (directory / "transcript.jsonl").write_text(
        "".join(record + "\n" for record in records), encoding="utf-8"
    )
    _write(directory, "events.json", events)
    provenance["window"] = window
    _write(directory, "provenance.json", provenance)
    return directory


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("scenario", nargs="?", choices=sorted(SCENARIOS))
    parser.add_argument("--endpoint", default=LOCAL_OLLAMA)
    parser.add_argument("--list", action="store_true", help="list the scenarios and exit")
    args = parser.parse_args(argv)
    if args.list or args.scenario is None:
        for name, scenario in SCENARIOS.items():
            print(f"{name}: {scenario.what}")
        return 0
    print(capture(args.scenario, args.endpoint))
    return 0


if __name__ == "__main__":
    sys.exit(main())
