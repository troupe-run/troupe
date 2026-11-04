"""The capture tool writes a fixture from an Ollama on this machine, and from nowhere else
(local-model-runner design D12)."""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from fake_ollama import Settings, calls, final, serving, tool_call

TOOL = Path(__file__).resolve().parents[1] / "tools" / "capture_ollama.py"


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("capture_ollama", TOOL)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["capture_ollama"] = module
    spec.loader.exec_module(module)
    return module


def test_a_capture_writes_the_fixtures_files_with_no_host_path(tmp_path: Path) -> None:
    capture = _tool()
    model = {"qwen3:0.6b": Settings().models["fake"]}
    answers = [
        calls(tool_call("Write", {"file_path": "out/hello.txt", "content": "hello"})),
        final("Done."),
    ]
    with serving(answers, Settings(models=model)) as fake:
        directory = capture.capture("success-with-tools", fake.url, tmp_path)
    assert sorted(p.name for p in directory.iterdir()) == [
        "answers.json",
        "events.json",
        "preflight.json",
        "provenance.json",
        "transcript.jsonl",
    ]
    events = json.loads((directory / "events.json").read_text(encoding="utf-8"))
    assert [event["type"] for event in events] == [
        "init",
        "tool_call",
        "tool_result",
        "turn",
        "result",
    ]
    assert all("runId" not in event and "durationMs" not in event for event in events)
    answers_written = json.loads((directory / "answers.json").read_text(encoding="utf-8"))
    assert [answer["status"] for answer in answers_written] == [200, 200]
    transcript = (directory / "transcript.jsonl").read_text(encoding="utf-8")
    assert "<scratch>" in transcript
    assert str(tmp_path) not in transcript
    provenance = json.loads((directory / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["ollamaVersion"] == "0.12.6"
    assert provenance["model"] == "qwen3:0.6b"


def test_a_preflight_capture_writes_only_the_preflight(tmp_path: Path) -> None:
    capture = _tool()
    with serving() as fake:
        directory = capture.capture("model-not-found", fake.url, tmp_path)
    assert sorted(p.name for p in directory.iterdir()) == ["preflight.json", "provenance.json"]
    preflight = json.loads((directory / "preflight.json").read_text(encoding="utf-8"))
    assert preflight["show"] is None


def test_a_capture_refuses_an_endpoint_that_isnt_on_this_machine(tmp_path: Path) -> None:
    capture = _tool()
    with pytest.raises(SystemExit, match="isn't on this machine"):
        capture.capture("success-with-tools", "http://example.com:11434", tmp_path)
    assert list(tmp_path.iterdir()) == []
