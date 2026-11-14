"""The fixtures: each replays through the fake endpoint and the real runner to the events it
expects, leaks no credential, says where it came from, and holds no secret (spec: anthropic-runner,
"Fixtures pair service output with protocol events", "Fixtures hold no secrets", "Fixtures that need
a working credential are captured by the owner"; design D12, D14)."""

import json
import re
import shutil
from pathlib import Path

import pytest

from anthropic_fixture_replay import ECHO, NAMES, load, replay
from anthropic_harness import CANARY, FIXTURES

REQUIRED = {
    "lm-studio-tool-loop",
    "lm-studio-context-refused",
    "lm-studio-conversation-cut",
    "lm-studio-output-limit",
    "lm-studio-broken-stream",
    "claude-tool-loop",
    "claude-context-refused",
    "claude-rejected-credential",
    "claude-rate-limit",
    "claude-overloaded",
    "claude-stream-error",
    "claude-refusal",
}
"""The fixtures the spec names: a tool loop against LM Studio and one against Claude's API (the
owner's capture), a context refusal from each, LM Studio's silent cut, the output limit, a broken
stream, and each way Claude's API fails that a fixture can show."""

SECRETS = {
    "an Anthropic key": re.compile(r"sk-ant-(?!troupe-capture-invalid)[A-Za-z0-9_\-]{8,}"),
    "a request id": re.compile(r"\breq_(?!scrubbed\b)[A-Za-z0-9]{8,}"),
    "an organisation id": re.compile(r"anthropic-organization-id", re.IGNORECASE),
    "a home directory": re.compile(
        r"/Users/[^/\s\"]+|/home/[^/\s\"]+|[A-Za-z]:\\{1,2}Users\\{1,2}"
    ),
    "a 1Password reference": re.compile(r"op://"),
}
"""What no fixture may hold, on any machine that captured it (spec: anthropic-runner, "Fixtures
hold no secrets")."""


def scan(directory: Path) -> list[str]:
    """Each line under ``directory`` holding something in SECRETS, as
    ``<directory>/<file>:<line> (<what>)``."""
    found = []
    for path in sorted(directory.rglob("*")):
        # A dotfile, such as Finder's .DS_Store, is git-ignored and never committed.
        if not path.is_file() or path.name.startswith("."):
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


def _result(name: str) -> dict[str, object]:
    events: list[dict[str, object]] = load(name, "expected.json")["events"]
    return events[-1]


def test_lm_studios_streamed_context_refusal_ends_with_context_length_unretried() -> None:
    # Requirement: A context-length refusal ends the run with context-length.
    expected = load("lm-studio-context-refused", "expected.json")
    assert expected["requests"] == 1
    result = _result("lm-studio-context-refused")
    assert (result["status"], result["reason"]) == ("error", "context-length")


def test_claudes_context_refusal_ends_with_context_length_unretried() -> None:
    # Requirement: A context-length refusal ends the run with context-length. Recorded from Claude's
    # API by the owner, with a working key (task 7.3).
    expected = load("claude-context-refused", "expected.json")
    assert expected["requests"] == 1
    result = _result("claude-context-refused")
    assert (result["status"], result["reason"]) == ("error", "context-length")
    assert "prompt is too long" in str(result["message"])


def test_claudes_tool_loop_was_recorded_with_a_working_key_and_succeeds() -> None:
    provenance = load("claude-tool-loop", "provenance.json")
    assert provenance["credential"] == "a working key from ANTHROPIC_API_KEY, never written"
    assert load("claude-tool-loop", "expected.json")["outcome"] == "succeeded"


def test_the_conversation_lm_studio_cut_ends_before_its_reply_is_acted_on() -> None:
    # Requirement: A reply made from a cut conversation is never acted on. The third reply asks for
    # a tool call; none follows the second's.
    expected = load("lm-studio-conversation-cut", "expected.json")
    assert expected["requests"] == 3
    calls = [e for e in expected["events"] if e["type"] == "tool_call"]
    assert len(calls) == 2
    result = _result("lm-studio-conversation-cut")
    assert (result["status"], result["reason"]) == ("error", "context-length")
    assert "4037" in str(result["message"])
    assert "4597" in str(result["message"])


def test_the_rejected_credential_fixture_used_no_working_credential() -> None:
    provenance = load("claude-rejected-credential", "provenance.json")
    assert "no working credential was used" in provenance["credential"]
    replies = json.loads((FIXTURES / "claude-rejected-credential" / "replies.json").read_text())
    assert replies[0]["status"] == 401


def test_no_fixture_holds_a_key_a_request_id_an_account_or_a_home_directory() -> None:
    assert scan(FIXTURES) == []


@pytest.mark.parametrize(
    ("planted", "what"),
    [
        ("sk-ant-api03-planted0123456789", "an Anthropic key"),
        ('"request_id": "req_011CVAbCdEf0123456789"', "a request id"),
        ('"anthropic-organization-id": "0123"', "an organisation id"),
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
    shutil.copytree(FIXTURES / "claude-refusal", copy / "claude-refusal")
    provenance = copy / "claude-refusal" / "provenance.json"
    provenance.write_text(provenance.read_text(encoding="utf-8") + planted + "\n", encoding="utf-8")
    lines = provenance.read_text(encoding="utf-8").splitlines()
    assert f"claude-refusal/provenance.json:{len(lines)} ({what})" in scan(copy)
