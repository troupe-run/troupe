"""Capture the mistralrs runner's fixtures from a real model (spec: mistralrs-runner, "Fixtures pair
real engine output with protocol events"; in-process-runner design D10).

Each case runs the real conversation, with the real engine, on a model file this machine has, and
writes ``fixtures/<case>/``:

- ``provenance.json``: the mistralrs version, the model's file name and SHA-256, the date and the
  tool.
- ``run.json``: the direction, options, onContextFull, the effects' write globs and the files the
  workspace starts with.
- ``responses.json``: each response as the engine returned it, serialised (engine.serialised).
- ``engine.json``: the model's length and each token count the tokenizer gave (by the SHA-256 of
  the text, its paths in placeholders), so a replay counts, and so bounds each answer, exactly as
  the real run did.
- ``expected.json``: the run's events and its transcript records' kinds, with the workspace and
  scratch paths as ``<workspace>`` and ``<scratch>``, the run id as ``<run>`` and durations as 0.

The tests replay ``responses.json`` through the engine stand-in and check the runner sends exactly
``expected.json``. Run it as ``uv run plugins/runner-mistralrs/tools/capture_mistralrs.py <model>
[case ...]``. It loads the model once per case: one heavy run at a time.
"""

import datetime
import hashlib
import json
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

from troupe_plugin_sdk import runner as p
from troupe_runner_mistralrs import engine
from troupe_runner_mistralrs.conversation import Conversation
from troupe_runner_mistralrs.options import parse_options
from troupe_runner_mistralrs.port import Answer, ChatRequest, Engine, LoadSpec

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
NOTES = "The launch code is BLUE-42.\n"
CASES: dict[str, dict[str, Any]] = {
    "tool-call": {
        "direction": "Call the Read tool with file_path notes.txt (a path relative to the "
        "workspace), then tell me the launch code it gives.",
        "files": {"notes.txt": NOTES},
    },
    "two-calls": {
        "direction": "Call the Read tool twice in one reply: once with file_path a.txt and once "
        "with file_path b.txt (paths relative to the workspace). Then say what each file says.",
        "files": {"a.txt": "alpha\n", "b.txt": "beta\n"},
    },
    "effects-refused": {
        "direction": "Call the Delete tool with file_path notes.txt (a path relative to the "
        "workspace) now. Don't answer before you have called it.",
        "files": {"notes.txt": NOTES},
    },
    "length-stop": {
        "direction": "Write a story of at least two thousand words about a lighthouse keeper.",
        "options": {"contextLength": 2048},
        "files": {},
    },
}
"""Each case: a direction (``{workspace}``, if used, is the run's workspace), and the options a
small model needs to follow it the same way each time. Every case sets temperature 0, think false
and a seed.

There is no compaction case: Qwen3-0.6B reads every file it's asked for in one reply, which leaves
no earlier turn's result to stub. Compaction is tested with the engine stand-in instead (design
D10)."""

BASE_OPTIONS = {"temperature": 0, "think": False, "seed": 7, "maxTurns": 5}


class Recording:
    """The real engine, keeping each response it returns."""

    def __init__(self, inner: Engine, workspace: str, scratch: str) -> None:
        self.inner = inner
        self.workspace = workspace
        self.scratch = scratch
        self.responses: list[dict[str, Any]] = []
        self.counts: dict[str, int] = {}

    @property
    def version(self) -> str:
        return self.inner.version

    def max_sequence_length(self) -> int | None:
        return self.inner.max_sequence_length()

    def count(self, text: str) -> int:
        tokens = self.inner.count(text)
        self.counts[text_key(normalised(text, self.workspace, self.scratch, "<run>"))] = tokens
        return tokens

    def chat(self, request: ChatRequest) -> Answer:
        answer = self.inner.chat(request)
        self.responses.append(dict(answer.record))
        return answer


def text_key(text: str) -> str:
    """The key a token count is recorded under: the SHA-256 of the text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Sink:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.kinds: list[str] = []

    def event(self, event: p.RunEvent) -> None:
        self.events.append(event.to_data())

    def transcript(self, kind: p.TranscriptKind, record: bytes) -> None:
        del record
        self.kinds.append(kind)

    def stopping(self) -> bool:
        return False


def normalised(value: Any, workspace: str, scratch: str, run_id: str) -> Any:  # noqa: ANN401
    """``value`` with the run's own paths, id and durations put in placeholders. On macOS a
    temporary directory is /private/var/...; /var/... names it too."""
    if isinstance(value, str):
        for path, placeholder in ((workspace, "<workspace>"), (scratch, "<scratch>")):
            value = value.replace(path, placeholder)
            value = value.replace(path.removeprefix("/private"), placeholder)
        return value.replace(run_id, "<run>")
    if isinstance(value, list):
        return [normalised(item, workspace, scratch, run_id) for item in value]
    if isinstance(value, dict):
        return {
            key: 0 if key == "durationMs" else normalised(item, workspace, scratch, run_id)
            for key, item in value.items()
        }
    return value


def capture(model: Path, name: str) -> None:
    case = CASES[name]
    options = {**BASE_OPTIONS, **case.get("options", {})}
    with tempfile.TemporaryDirectory() as workspace, tempfile.TemporaryDirectory() as scratch:
        for file, content in case["files"].items():
            (Path(workspace) / file).write_text(content, encoding="utf-8")
        run_id = str(uuid.uuid4())
        workspace = str(Path(workspace).resolve())
        scratch = str(Path(scratch).resolve())
        start = p.RunStartParams.from_data(
            {
                "runId": run_id,
                "direction": case["direction"].replace("{workspace}", workspace),
                "workspace": workspace,
                "options": options,
                "limits": {"eventMaxBytes": 65536},
                "effects": {"write": [], "delete": [], "move": []},
                "scratch": scratch,
                "onContextFull": case.get("onContextFull", "fail"),
                "runtime": {"name": "mistralrs", "model": str(model), "credential": False},
            }
        )
        recordings: list[Recording] = []

        def load(spec: LoadSpec) -> Recording:
            kv = spec.kv_tokens
            if sys.platform == "darwin":
                kv = options.get("contextLength", 16384)
            recording = Recording(
                engine.load(LoadSpec(spec.model, spec.seed, kv)), workspace, scratch
            )
            recordings.append(recording)
            return recording

        sink = Sink()
        Conversation(
            start=start,
            options=parse_options(options),
            model="<model>",
            spec=LoadSpec(model, options.get("seed")),
            engine_version=engine.ENGINE_VERSION,
            loader=load,
            sink=sink,
        ).run()
        out = FIXTURES / name
        out.mkdir(parents=True, exist_ok=True)
        provenance = {
            "mistralrs": engine.ENGINE_VERSION,
            "model": model.name,
            "sha256": hashlib.sha256(model.read_bytes()).hexdigest(),
            "date": datetime.date.today().isoformat(),
            "tool": "plugins/runner-mistralrs/tools/capture_mistralrs.py",
        }
        run = {
            "direction": case["direction"],
            "options": options,
            "onContextFull": case.get("onContextFull", "fail"),
            "files": case["files"],
        }
        expected = {
            "events": normalised(sink.events, workspace, scratch, run_id),
            "transcriptKinds": sink.kinds,
        }
        recording = recordings[0]
        responses = normalised(recording.responses, workspace, scratch, run_id)
        responses = json.loads(
            json.dumps(responses).replace(json.dumps(str(model))[1:-1], "<model>")
        )
        engine_data = {
            "maxSequenceLength": recording.max_sequence_length(),
            "counts": recording.counts,
        }
        for file, data in (
            ("provenance.json", provenance),
            ("run.json", run),
            ("responses.json", responses),
            ("engine.json", engine_data),
            ("expected.json", expected),
        ):
            (out / file).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", "utf-8")
        result = sink.events[-1]
        print(
            f"{name}: {result.get('status')} {result.get('reason', '')} {len(responses)} responses"
        )


def main() -> None:
    model = Path(sys.argv[1]).resolve()
    for name in sys.argv[2:] or list(CASES):
        capture(model, name)


if __name__ == "__main__":
    main()
