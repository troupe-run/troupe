"""The Ollama fixtures: real Ollama output, replayed through the runner, gives exactly the records
and events they hold; each says where it came from; none holds a secret or a host path (spec:
ollama-runner, "Fixtures pair real Ollama output with protocol events"; local-model-runner design
D12)."""

import json
import re
from pathlib import Path

import pytest

from fixture_replay import fixture_records, load, names, replay
from ollama_harness import FIXTURES

REFUSALS = {
    "model-not-found": "ollama.model-not-found",
    "no-tools-capability": "ollama.model-without-tools",
}
"""The fixtures whose run the preflight refuses, and the code it refuses them with."""

RUNS = [name for name in names() if name not in REFUSALS]

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
        "model-not-found",
        "no-tools-capability",
        "server-retries",
        "network-retries",
        "stream-error",
    }


@pytest.mark.parametrize("name", RUNS)
def test_replaying_a_fixture_gives_exactly_its_records_and_events(
    name: str, tmp_path: Path
) -> None:
    replayed = replay(name, tmp_path)
    assert replayed.refused is None
    assert replayed.records == fixture_records(name)
    assert replayed.events == load(name, "events.json")


@pytest.mark.parametrize("name", sorted(REFUSALS))
def test_a_preflight_fixture_is_refused_with_its_code(name: str, tmp_path: Path) -> None:
    replayed = replay(name, tmp_path)
    assert replayed.refused is not None
    assert replayed.refused["code"] == REFUSALS[name]


def test_the_context_overflow_fixture_is_ollamas_refusal_naming_the_window() -> None:
    (answer,) = load("context-overflow", "answers.json")
    assert answer["status"] == 400
    assert "exceeds the available context size (512 tokens)" in answer["body"]
    result = load("context-overflow", "events.json")[-1]
    assert result["status"] == "error"
    assert "context window is 512 tokens" in result["message"]


def test_the_thinking_fixtures_thinking_is_in_its_transcript_only() -> None:
    assert any('"thinking"' in record for record in fixture_records("thinking"))
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
