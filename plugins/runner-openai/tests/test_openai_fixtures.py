"""The fixtures: each replays through the fake endpoint and the real runner to the events it
expects, leaks no credential, says where it came from, and holds no secret (spec: openai-runner,
"Fixtures pair service output with protocol events", "Fixtures hold no secrets", "Failure fixtures
are captured without a real credential", "The credential goes only in the Authorization header";
design D13)."""

import re
import shutil
from pathlib import Path

import pytest

from openai_fixture_replay import ECHO, NAMES, load, replay
from openai_harness import CANARY, FIXTURES

REQUIRED = {
    "openai-tool-loop",
    "ollama-tool-loop",
    "rejected-credential",
    "rate-limit",
    "server-error",
    "broken-stream",
    "incomplete",
    "refusal",
    "failed-response",
}
"""The fixtures the spec names: a successful tool loop against OpenAI and one against local Ollama,
and each way a hosted service fails that a fixture can show."""

SECRET = re.compile(r"sk-[A-Za-z0-9_\-]{8,}")
"""A string shaped like an OpenAI key."""


def scan(directory: Path) -> list[str]:
    """Each line in a fixture directory holding something shaped like a key, or the capturing
    host's home directory, as ``<fixture>/<file>:<line>``."""
    home = str(Path.home())
    found = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if SECRET.search(line) or home in line:
                found.append(f"{path.parent.name}/{path.name}:{number}")
    return found


def test_every_required_fixture_is_there() -> None:
    assert set(NAMES) >= REQUIRED


@pytest.mark.parametrize("name", NAMES)
def test_each_fixture_replays_to_its_expected_events_and_writes_no_part_of_the_credential(
    name: str, tmp_path: Path
) -> None:
    expected = load(name, "expected.json")
    replayed = replay(name, tmp_path)
    assert replayed.requests == expected["requests"]
    assert replayed.events == expected["events"]
    written = replayed.written
    for secret in (CANARY, CANARY[:-1], CANARY[1:], ECHO):
        assert secret.encode() not in written


@pytest.mark.parametrize("name", NAMES)
def test_each_fixtures_provenance_names_its_service_and_whether_it_was_recorded_derived_or_built(
    name: str,
) -> None:
    provenance = load(name, "provenance.json")
    assert provenance["service"]
    assert provenance["model"]
    assert provenance["how"].split(":")[0].split(" ")[0] in ("recorded", "derived", "built")
    assert provenance["credential"]


def test_the_rejected_credential_fixture_used_no_working_credential() -> None:
    provenance = load("rejected-credential", "provenance.json")
    assert "no working credential was used" in provenance["credential"]
    assert "[credential]" in (FIXTURES / "rejected-credential" / "replies.json").read_text()


def test_no_fixture_holds_a_key_or_the_capturing_hosts_home() -> None:
    assert scan(FIXTURES) == []


def test_the_scan_names_the_fixture_and_line_of_a_planted_key(tmp_path: Path) -> None:
    copy = tmp_path / "fixtures"
    shutil.copytree(FIXTURES / "refusal", copy / "refusal")
    provenance = copy / "refusal" / "provenance.json"
    provenance.write_text(
        provenance.read_text(encoding="utf-8") + "sk-proj-planted0123456789\n", encoding="utf-8"
    )
    lines = provenance.read_text(encoding="utf-8").splitlines()
    assert scan(copy) == [f"refusal/provenance.json:{len(lines)}"]
