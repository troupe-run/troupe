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

DATA = Path(__file__).parent / "data"
"""The raw recordings the fixtures were made from, scanned as well."""

SECRETS = {
    "an OpenAI key": re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    "an organisation or project id": re.compile(
        r"\borg-[A-Za-z0-9]{8,}|\bproj_[A-Za-z0-9]{8,}|openai-(?:organization|project)",
        re.IGNORECASE,
    ),
    "a home directory": re.compile(
        r"/Users/[^/\s\"]+|/home/[^/\s\"]+|[A-Za-z]:\\{1,2}Users\\{1,2}"
    ),
    "a 1Password reference": re.compile(r"op://"),
}
"""What no fixture or recording may hold, on any machine that captured it (spec: openai-runner,
"Fixtures hold no secrets")."""


def scan(directory: Path) -> list[str]:
    """Each line under ``directory`` holding something in SECRETS, as
    ``<directory>/<file>:<line> (<what>)``."""
    found = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for what, pattern in SECRETS.items():
                if pattern.search(line):
                    found.append(f"{path.parent.name}/{path.name}:{number} ({what})")
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


def test_no_fixture_or_recording_holds_a_key_an_account_id_or_a_home_directory() -> None:
    assert scan(FIXTURES) == []
    assert scan(DATA) == []


@pytest.mark.parametrize(
    ("planted", "what"),
    [
        ("sk-proj-planted0123456789", "an OpenAI key"),
        ('"openai-organization": "org-AbCdEf0123456789"', "an organisation or project id"),
        ("/Users/someone/troupe/notes.txt", "a home directory"),
        ("/home/runner/work/troupe", "a home directory"),
        ("C:\\Users\\someone\\troupe", "a home directory"),
        ("op://vault/item/credential", "a 1Password reference"),
    ],
)
def test_the_scan_names_the_file_line_and_kind_of_whatever_is_planted(
    tmp_path: Path, planted: str, what: str
) -> None:
    copy = tmp_path / "fixtures"
    shutil.copytree(FIXTURES / "refusal", copy / "refusal")
    provenance = copy / "refusal" / "provenance.json"
    provenance.write_text(provenance.read_text(encoding="utf-8") + planted + "\n", encoding="utf-8")
    lines = provenance.read_text(encoding="utf-8").splitlines()
    assert f"refusal/provenance.json:{len(lines)} ({what})" in scan(copy)
