"""The capture tool writes a fixture from an Ollama on this machine, and from nowhere else
(local-model-runner design D12).

Its tests that stay in their own process are in unit/test_ollama_capture_unit.py."""

import json
from pathlib import Path

from fake_ollama import Settings, calls, final, serving, tool_call
from ollama_capture_shared import _tool


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
    # The replay compares the runner's version as a placeholder, so the capture writes it.
    assert events[0]["runner"]["version"] == "<package version>"
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


def test_a_compaction_capture_records_its_on_context_full(tmp_path: Path) -> None:
    capture = _tool()
    model = {"qwen3:0.6b": Settings().models["fake"]}
    with serving([final("Done.")], Settings(models=model)) as fake:
        directory = capture.capture("context-compacted", fake.url, tmp_path)
    provenance = json.loads((directory / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["onContextFull"] == "compact"
