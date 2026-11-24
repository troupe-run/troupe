"""The Ollama fixtures, read from their files: there is one for each shape, each named case holds
what Ollama sent and the outcome it should give, each records its Ollama version, model, date and
how it was made, and none holds a secret or a host path (spec: ollama-runner, "Fixtures pair real
Ollama output with protocol events"; local-model-runner design D12).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_ollama_fixtures_integration.py."""

import json
import re
from pathlib import Path

import pytest

from fixture_replay import fixture_records, load, names
from ollama_harness import FIXTURES
from troupe_plugin_sdk.compaction import stub

SECRET_PATTERNS = {
    "bearer credential": re.compile(r"Bearer\s+\S"),
    "macOS home directory": re.compile(r"/Users/[^/\"\s]+"),
    "Linux home directory": re.compile(r"/home/[^/\"\s]+"),
    "Windows home directory": re.compile(r"[A-Za-z]:\\\\+Users\\\\+"),
    # A pattern to find temporary host paths, not a use of one.
    "host temporary path": re.compile(r"/tmp/|/private/var/|/var/folders/|\\\\Temp\\\\"),  # noqa: S108
}


def scan(directory: Path, home: str = str(Path.home())) -> list[str]:
    """Each line of each file in ``directory`` matching a secret pattern, as file:line: what."""
    found: list[str] = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            hits = [name for name, pattern in SECRET_PATTERNS.items() if pattern.search(line)]
            if home in line:
                hits.append("the capturing user's home directory")
            found.extend(f"{path.name}:{number}: {hit}" for hit in hits)
    return found


def test_there_are_fixtures_for_each_shape() -> None:
    assert set(names()) == {
        "success-with-tools",
        "refused-by-effects",
        "thinking",
        "context-overflow",
        "context-compacted",
        "context-compaction-exhausted",
        "cut-answer",
        "cut-tool-call",
        "model-not-found",
        "no-tools-capability",
        "server-retries",
        "network-retries",
        "stream-error",
    }


def test_the_context_overflow_fixture_is_ollamas_refusal_naming_the_window() -> None:
    (answer,) = load("context-overflow", "answers.json")
    assert answer["status"] == 400
    assert "exceeds the available context size (512 tokens)" in answer["body"]
    result = load("context-overflow", "events.json")[-1]
    assert result["status"] == "error"
    assert "context window is 512 tokens" in result["message"]


def test_the_compacted_fixture_stubs_old_results_reports_each_compaction_and_finishes() -> None:
    # Requirement: A run told compact removes old tool results before a request that wouldn't
    # fit (compaction-opt-in).
    events = load("context-compacted", "events.json")
    contexts = [e for e in events if e["type"] == "context"]
    assert len(contexts) == 2
    for context in contexts:
        assert (context["kind"], context["by"]) == ("truncated", "runner")
        assert context["messagesBefore"] == context["messagesAfter"]
        assert "tokensBefore" not in context
    assert (events[-1]["type"], events[-1]["status"]) == ("result", "ok")
    sent = [json.loads(line)["record"] for line in fixture_records("context-compacted")]
    assert any(stub("Read") in record for record in sent)


def test_the_exhausted_fixture_ends_with_context_length_and_no_context_event() -> None:
    # Requirement: A run told compact compacts after a refusal and asks again (nothing left).
    events = load("context-compaction-exhausted", "events.json")
    assert [e["type"] for e in events] == ["init", "result"]
    result = events[-1]
    assert (result["status"], result["reason"]) == ("error", "context-length")
    assert "compaction found nothing more to remove" in result["message"]
    assert load("context-compaction-exhausted", "provenance.json")["onContextFull"] == "compact"


@pytest.mark.parametrize("name", ["cut-answer", "cut-tool-call"])
def test_a_cut_fixture_is_ollama_ending_its_answer_with_length_and_the_run_with_output_limit(
    name: str,
) -> None:
    (answer,) = load(name, "answers.json")
    assert json.loads(answer["lines"][-1])["done_reason"] == "length"
    events = load(name, "events.json")
    assert [event["type"] for event in events if event["type"] == "tool_call"] == []
    assert (events[-1]["status"], events[-1]["reason"]) == ("error", "output-limit")
    assert (
        f"context window of {load(name, 'provenance.json')['window']} tokens"
        in (events[-1]["message"])
    )


def test_ollama_sends_nothing_of_a_tool_call_it_cut() -> None:
    """What Ollama 0.40.14 sends for a cut call (ollama-output-limit design D4): it holds the
    call back. The answer is one done line, with no text and no tool_calls, though the model
    produced tokens."""
    (answer,) = load("cut-tool-call", "answers.json")
    (line,) = [json.loads(line) for line in answer["lines"]]
    assert line["message"]["content"] == ""
    assert "tool_calls" not in line["message"]
    assert line["eval_count"] > 0


def test_the_thinking_fixtures_thinking_is_in_its_transcript_only() -> None:
    assert any('"thinking"' in json.loads(line)["record"] for line in fixture_records("thinking"))
    assert all("thinking" not in json.dumps(event) for event in load("thinking", "events.json"))


@pytest.mark.parametrize("name", names())
def test_every_fixture_records_its_ollama_version_model_date_and_how_it_was_made(
    name: str,
) -> None:
    provenance = load(name, "provenance.json")
    assert re.fullmatch(r"\d+\.\d+\.\d+", provenance["ollamaVersion"])
    assert provenance["model"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", provenance["date"])
    assert provenance["command"]
    assert provenance["credential"]
    assert provenance["scrubbing"]
    assert provenance["events"]
    assert provenance["what"]


@pytest.mark.parametrize("name", names())
def test_a_committed_fixture_holds_no_secret_or_host_path(name: str) -> None:
    assert scan(FIXTURES / name) == []


@pytest.mark.parametrize(
    ("planted", "what"),
    [
        ('"Authorization: Bearer abc"', "bearer credential"),
        ('"cwd /Users/someone/project"', "macOS home directory"),
        ('"cwd /home/someone/project"', "Linux home directory"),
        ('"cwd C:\\\\Users\\\\someone"', "Windows home directory"),
        ('"scratch /private/var/folders/x"', "host temporary path"),
    ],
)
def test_the_scan_names_the_file_and_line_of_a_planted_secret(
    tmp_path: Path, planted: str, what: str
) -> None:
    (tmp_path / "transcript.jsonl").write_text('"fine"\n' + planted + "\n", encoding="utf-8")
    assert f"transcript.jsonl:2: {what}" in scan(tmp_path)
