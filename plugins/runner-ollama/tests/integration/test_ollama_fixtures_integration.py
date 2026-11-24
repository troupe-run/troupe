"""Each Ollama fixture replayed through the runner gives exactly the records and events it holds,
and a fixture whose run the preflight refuses is refused with its code (spec: ollama-runner,
"Fixtures pair real Ollama output with protocol events"; local-model-runner design D12).

Its tests that stay in their own process are in unit/test_ollama_fixtures.py."""

from pathlib import Path

import pytest

from fixture_replay import fixture_records, load, names, replay

REFUSALS = {
    "model-not-found": "ollama.model-not-found",
    "no-tools-capability": "ollama.model-without-tools",
}
"""The fixtures whose run the preflight refuses, and the code it refuses them with."""

RUNS = [name for name in names() if name not in REFUSALS]


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
