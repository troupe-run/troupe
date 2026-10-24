"""The Claude Code fixtures hold no secrets and record their provenance (spec:
claude-code-runner)."""

import json
import re
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "claude-code"
NAMES = sorted(path.name for path in FIXTURES.iterdir() if path.is_dir())

SECRET_PATTERNS = {
    "Anthropic API key": re.compile(r"sk-ant-"),
    "OAuth token": re.compile(r"sk-ant-oat|oat01"),
    "bearer credential": re.compile(r"Bearer\s+\S"),
    "macOS home directory": re.compile(r"/Users/[^/\"\s]+"),
    "Linux home directory": re.compile(r"/home/[^/\"\s]+"),
    "Windows home directory": re.compile(r"[A-Za-z]:\\\\+Users\\\\+"),
    # A pattern to find temporary host paths, not a use of one.
    "host temporary path": re.compile(r"/tmp/|/private/var/|/var/folders/|\\\\Temp\\\\"),  # noqa: S108
    # In a recording the native line is a JSON string, so its quotes are escaped.
    "account usage": re.compile(r'utilization\\?":\s*(?!0\.5\b)[0-9.]+'),
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


def test_there_are_fixtures_for_each_failure_shape() -> None:
    assert {
        "is-error-success-subtype",
        "auth-retries",
        "terminated-no-result",
        "success-with-tools",
    } <= set(NAMES)


@pytest.mark.parametrize("name", NAMES)
def test_a_committed_fixture_holds_no_secret_or_home_path(name: str) -> None:
    assert scan(FIXTURES / name) == []


@pytest.mark.parametrize(
    ("planted", "what"),
    [
        ('{"transcript": "key sk-ant-api03-abc"}', "Anthropic API key"),
        ('{"transcript": "Authorization: Bearer abc"}', "bearer credential"),
        ('{"transcript": "cwd /Users/someone/project"}', "macOS home directory"),
        ('{"transcript": "cwd /home/someone/project"}', "Linux home directory"),
        ('{"transcript": "cwd C:\\\\Users\\\\someone"}', "Windows home directory"),
        ('{"transcript": "socket /tmp/cc-socks/1.sock"}', "host temporary path"),
        ('{"transcript": "{\\"utilization\\":0.08}"}', "account usage"),
    ],
)
def test_the_scan_names_the_fixture_and_line_of_a_planted_secret(
    tmp_path: Path, planted: str, what: str
) -> None:
    (tmp_path / "recording.jsonl").write_text(
        '{"transcript": "fine"}\n' + planted + "\n", encoding="utf-8"
    )
    assert f"recording.jsonl:2: {what}" in scan(tmp_path)


def test_the_scan_finds_the_capturing_users_home(tmp_path: Path) -> None:
    (tmp_path / "recording.jsonl").write_text(
        '{"transcript": "/srv/capturer/x"}\n', encoding="utf-8"
    )
    assert scan(tmp_path, home="/srv/capturer") == [
        "recording.jsonl:1: the capturing user's home directory"
    ]


@pytest.mark.parametrize("name", NAMES)
def test_every_fixture_records_its_version_date_command_and_scrubbing(name: str) -> None:
    provenance = json.loads((FIXTURES / name / "provenance.json").read_text(encoding="utf-8"))
    assert re.fullmatch(r"\d+\.\d+\.\d+", provenance["claudeCodeVersion"])
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", provenance["date"])
    assert provenance["command"][:2] == ["claude", "-p"]
    assert provenance["scrubbing"]
    assert "credential" in provenance


@pytest.mark.parametrize("name", NAMES)
def test_every_fixture_pairs_each_native_line_with_events_and_states_its_outcome(name: str) -> None:
    lines = [
        json.loads(line)
        for line in (FIXTURES / name / "recording.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert lines[0].keys() >= {"transcript"}
    assert any("event" in line for line in lines)
    expected = json.loads((FIXTURES / name / "expected.json").read_text(encoding="utf-8"))
    assert {"outcome", "errorCode", "exitCode", "withoutFailFast"} <= expected.keys()
