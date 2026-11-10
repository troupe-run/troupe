"""Each recorded fixture, replayed by the fake LM Studio, gives exactly the events it pairs with
(spec: lm-studio-runner, "Fixtures pair real LM Studio exchanges with protocol events")."""

import json
from pathlib import Path
from typing import Any

import pytest

from fake_lm_studio import FIXTURES, FakeLMStudio, script_of
from lm_studio_harness import Session, events, transcript

NAMES = sorted(path.name for path in FIXTURES.iterdir() if (path / "exchange.json").is_file())
VERSION = "<package version>"


def replay(name: str, tmp_path: Path) -> dict[str, Any]:
    """The run a fixture's recording plays back to: its events (without the run id, and the
    runner's version as a placeholder) and its transcript's kinds."""
    fixture = FIXTURES / name
    run = json.loads((fixture / "run.json").read_text(encoding="utf-8"))
    files = json.loads((fixture / "workspace.json").read_text(encoding="utf-8"))
    workspace = tmp_path / "ws"
    workspace.mkdir()
    for path, content in files.items():
        target = workspace / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content.replace("\\n", "\n"), encoding="utf-8")
    with FakeLMStudio(script_of(name)) as fake:
        session = Session(workspace)
        answer = session.start(
            fake.endpoint,
            options=run["options"],
            model=run["model"],
            direction=run["direction"],
            effects={k: v for k, v in run["effects"].items() if v},
        )
        assert "result" in answer, answer
        messages = session.until_result()
        assert session.shutdown() == 0
        assert fake.mismatches == []
        session.validate_all()
    played = []
    for event in events(messages):
        event = {k: v for k, v in event.items() if k != "runId"}
        if event["type"] == "init":
            event["runner"] = {**event["runner"], "version": VERSION}
        played.append(event)
    return {"events": played, "transcriptKinds": [r["kind"] for r in transcript(messages)]}


@pytest.mark.parametrize("name", NAMES)
def test_a_recorded_fixture_replayed_gives_exactly_its_events(name: str, tmp_path: Path) -> None:
    expected = json.loads((FIXTURES / name / "expected.json").read_text(encoding="utf-8"))
    assert replay(name, tmp_path) == expected


@pytest.mark.parametrize("name", NAMES)
def test_a_fixture_holds_no_passkey_and_no_path_of_the_capturing_host(name: str) -> None:
    text = "".join(path.read_text(encoding="utf-8") for path in (FIXTURES / name).iterdir())
    exchange = json.loads((FIXTURES / name / "exchange.json").read_text(encoding="utf-8"))
    auths = [f["message"] for s in exchange for f in s["frames"] if "authVersion" in f["message"]]
    assert auths
    assert {(a["clientIdentifier"], a["clientPasskey"]) for a in auths} == {
        ("client-identifier", "client-passkey")
    }
    for marker in ("/Users/", "/home/", "C:\\\\Users", "/var/folders/", "lms-capture-"):
        assert marker not in text


@pytest.mark.parametrize("name", NAMES)
def test_a_fixture_says_where_it_came_from(name: str) -> None:
    provenance = json.loads((FIXTURES / name / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["source"] == "recorded"
    assert {"lmStudio", "lmstudio", "model", "date"} <= set(provenance)
