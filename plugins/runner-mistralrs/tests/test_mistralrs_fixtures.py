"""Each fixture, captured from a real model by tools/capture_mistralrs.py, replays through the
engine stand-in to exactly the events and transcript kinds the real run gave (spec:
mistralrs-runner, "Fixtures pair real engine output with protocol events"; in-process-runner design
D10)."""

import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from stand_in import StandIn
from test_mistralrs_conversation import Sink
from troupe_plugin_sdk import runner as p
from troupe_runner_mistralrs.conversation import Conversation
from troupe_runner_mistralrs.options import parse_options
from troupe_runner_mistralrs.port import LoadSpec

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CASES = sorted(path.name for path in FIXTURES.iterdir() if path.is_dir())


def _load(case: str, name: str) -> Any:  # noqa: ANN401 - JSON
    return json.loads((FIXTURES / case / name).read_text(encoding="utf-8"))


def _filled(value: Any, workspace: str, scratch: str) -> Any:  # noqa: ANN401 - JSON
    """``value`` with the placeholders put back as this replay's paths."""
    text = json.dumps(value)
    for placeholder, path in (("<workspace>", workspace), ("<scratch>", scratch)):
        text = text.replace(placeholder, json.dumps(path)[1:-1])
    return json.loads(text)


def _normalised(value: Any, workspace: str, scratch: str, run_id: str) -> Any:  # noqa: ANN401
    text = json.dumps(value)
    for path, placeholder in ((workspace, "<workspace>"), (scratch, "<scratch>")):
        text = text.replace(json.dumps(path)[1:-1], placeholder)
    data = json.loads(text.replace(run_id, "<run>"))
    for event in data:
        if "durationMs" in event:
            event["durationMs"] = 0
    return data


def test_there_is_a_fixture_for_each_case_the_capture_tool_has() -> None:
    assert CASES == ["effects-refused", "length-stop", "tool-call", "two-calls"]


@pytest.mark.parametrize("case", CASES)
def test_each_fixture_has_its_provenance(case: str) -> None:
    provenance = _load(case, "provenance.json")
    assert provenance["mistralrs"] == "0.9.5"
    assert provenance["model"] == "Qwen3-0.6B-Q8_0.gguf"
    assert len(provenance["sha256"]) == 64
    assert provenance["date"]


@pytest.mark.parametrize("case", CASES)
def test_a_fixture_replayed_gives_exactly_its_events_and_transcript_kinds(
    case: str, tmp_path: Path
) -> None:
    run = _load(case, "run.json")
    engine = _load(case, "engine.json")
    expected = _load(case, "expected.json")
    workspace, scratch = tmp_path / "w", tmp_path / "s"
    workspace.mkdir()
    scratch.mkdir()
    for name, content in run["files"].items():
        (workspace / name).write_text(content, encoding="utf-8")
    run_id = str(uuid.uuid4())
    start = p.RunStartParams.from_data(
        {
            "runId": run_id,
            "direction": run["direction"].replace("{workspace}", str(workspace)),
            "workspace": str(workspace),
            "options": run["options"],
            "limits": {"eventMaxBytes": 65536},
            "effects": {"write": [], "delete": [], "move": []},
            "scratch": str(scratch),
            "onContextFull": run["onContextFull"],
            "runtime": {"name": "mistralrs", "model": "/m.gguf", "credential": False},
        }
    )
    stand_in = StandIn(
        {
            "responses": _filled(_load(case, "responses.json"), str(workspace), str(scratch)),
            "maxSequenceLength": engine["maxSequenceLength"],
            "counts": engine["counts"],
            "paths": {"<workspace>": str(workspace), "<scratch>": str(scratch)},
        }
    )
    sink = Sink()
    Conversation(
        start=start,
        options=parse_options(run["options"]),
        model="<model>",
        spec=LoadSpec(Path("/m.gguf")),
        engine_version="0.9.5",
        loader=stand_in.load,
        sink=sink,
    ).run()
    assert _normalised(sink.events, str(workspace), str(scratch), run_id) == expected["events"]
    assert [kind for kind, _ in sink.records] == expected["transcriptKinds"]
    if (workspace / "notes.txt").exists() or "notes.txt" in run["files"]:
        assert (workspace / "notes.txt").exists()  # a refused Delete deleted nothing
