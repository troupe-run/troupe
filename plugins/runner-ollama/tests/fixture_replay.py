"""Replay a fixture: serve its recorded Ollama answers from the fake, and run the runner process
against them (local-model-runner design D12).

A fixture is a directory under fixtures/ollama/ holding ``preflight.json`` (what Ollama answered to
/api/version and /api/show), ``provenance.json`` (the run's options, direction and effects), and,
for a run that gets past the preflight, ``answers.json`` (each /api/chat answer), with the
``transcript.jsonl`` and ``events.json`` the runner sent. The workspace's and scratch directory's
paths are ``<workspace>`` and ``<scratch>`` in the fixture.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fake_ollama import Answer, FakeOllama, Settings
from ollama_harness import FIXTURES, Session

FILES = {"context-overflow": {"notes.txt": "A line of notes.\n" * 200}}
"""The files a fixture's workspace starts with, as its capture made them."""


@dataclass(frozen=True)
class Replayed:
    """What the runner sent for a fixture, in the fixture's form."""

    refused: dict[str, Any] | None
    """run/start's error data, when the preflight refused the run."""
    records: list[str]
    events: list[dict[str, Any]]


def names() -> list[str]:
    return sorted(path.name for path in FIXTURES.iterdir() if path.is_dir())


def load(name: str, file: str) -> Any:  # noqa: ANN401 - JSON
    return json.loads((FIXTURES / name / file).read_text(encoding="utf-8"))


def answers(name: str) -> list[Answer]:
    path = FIXTURES / name / "answers.json"
    if not path.exists():
        return []
    played = []
    for answer in json.loads(path.read_text(encoding="utf-8")):
        if answer["status"] != 200:
            played.append(Answer(status=answer["status"], body=answer["body"].encode()))
        else:
            played.append(
                Answer(
                    [line.encode() for line in answer["lines"]],
                    close_after=answer.get("closeAfter"),
                )
            )
    return played


def settings(name: str) -> Settings:
    preflight = load(name, "preflight.json")
    models = {} if preflight["show"] is None else {preflight["model"]: preflight["show"]}
    return Settings(version=preflight["version"], models=models)


def _scrub(text: str, workspace: Path, scratch: Path) -> str:
    for path, placeholder in ((scratch, "<scratch>"), (workspace, "<workspace>")):
        text = text.replace(json.dumps(str(path))[1:-1], placeholder).replace(
            str(path), placeholder
        )
    return text


def replay(name: str, root: Path) -> Replayed:
    """Run the runner on fixture ``name`` in a workspace under ``root``."""
    provenance = load(name, "provenance.json")
    workspace = root / "workspace"
    workspace.mkdir()
    for relative, content in FILES.get(name, {}).items():
        (workspace / relative).write_text(content, encoding="utf-8")
    fake = FakeOllama(answers(name), settings(name)).start()
    session = Session(workspace)
    try:
        options = {**provenance["options"], "endpoint": fake.url}
        response = session.start(
            options, direction=provenance.get("direction", ""), effects=provenance.get("effects")
        )
        if "error" in response:
            return Replayed(response["error"]["data"], [], [])
        messages = session.until_result()
        session.request("shutdown", {})
        session.wait()
        session.validate_all()
    finally:
        session.kill()
        fake.stop()
    scratch = session.scratch()
    records = [
        _scrub(m["params"]["record"], workspace, scratch)
        for m in messages
        if m.get("method") == "run/transcript"
    ]
    events = []
    for message in messages:
        if message.get("method") != "run/event":
            continue
        event = dict(message["params"])
        event.pop("runId")
        event.pop("durationMs", None)
        events.append(json.loads(_scrub(json.dumps(event, ensure_ascii=False), workspace, scratch)))
    return Replayed(None, records, events)


def fixture_records(name: str) -> list[str]:
    text = (FIXTURES / name / "transcript.jsonl").read_text(encoding="utf-8")
    return text.splitlines()


def write_recorded(name: str, root: Path) -> Replayed:
    """Replay ``name`` and write what the runner sent as its transcript.jsonl and events.json: for
    a hand-written fixture's answers, whose events are then reviewed by hand."""
    replayed = replay(name, root)
    directory = FIXTURES / name
    (directory / "transcript.jsonl").write_text(
        "".join(record + "\n" for record in replayed.records), encoding="utf-8"
    )
    (directory / "events.json").write_text(
        json.dumps(replayed.events, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return replayed
