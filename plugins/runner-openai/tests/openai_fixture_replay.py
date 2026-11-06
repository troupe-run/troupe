"""Replaying a fixture through the fake endpoint and the real runner process (openai-style-runner
design D13).

A fixture in ``fixtures/responses/<name>/`` holds ``replies.json`` (the service's answers, request
by request: a status, the headers kept, and the stream's lines or the body; ``cut`` ends a stream
there), ``provenance.json`` (where they came from, and the workspace files the run reads) and
``expected.json`` (the run events the runner sends for them, without their run id). Every replay
runs on TEST_LIMITS with a canary credential, so a fixture's run can be scanned for it.
"""

import json
from pathlib import Path
from typing import Any

from fake_endpoint import Cut, FakeEndpoint, Reply
from openai_harness import CANARY, FIXTURES, TEST_LIMITS, Session

NAMES = sorted(path.name for path in FIXTURES.iterdir() if path.is_dir())
ECHO = f"{CANARY[:7]}*********{CANARY[-4:]}"
"""How a service echoes the run's key, part masked, as OpenAI's 401 does: a fixture's scrubbed
``[credential]`` is played back as this, so the runner's masking is what keeps it out."""
DIRECTION = "Read notes/todo.txt, then tell me in one line what it says."


def load(name: str, file: str) -> Any:  # noqa: ANN401 - JSON
    return json.loads((FIXTURES / name / file).read_text(encoding="utf-8"))


def replies(name: str) -> list[Reply]:
    """The fixture's answers, as the fake endpoint serves them."""
    played: list[Reply] = []
    for answer in load(name, "replies.json"):
        headers = [tuple(header) for header in answer.get("headers", [])]
        if "lines" in answer:
            lines: list[Any] = [line.replace("[credential]", ECHO) for line in answer["lines"]]
            if answer.get("cut"):
                lines.append(Cut())
            played.append(Reply(answer["status"], headers=headers, lines=lines))
        else:
            body = answer["body"].replace("[credential]", ECHO).encode("utf-8")
            played.append(Reply(answer["status"], headers=headers, body=body))
    return played


class Replayed:
    """A fixture's replay: what the runner sent, and what it wrote."""

    def __init__(self, session: Session, messages: list[dict[str, Any]], requests: int) -> None:
        self.session = session
        self.messages = messages
        self.requests = requests

    @property
    def events(self) -> list[dict[str, Any]]:
        """The run events, without their run id."""
        return [
            {k: v for k, v in m["params"].items() if k != "runId"}
            for m in self.messages
            if m.get("method") == "run/event"
        ]

    @property
    def written(self) -> bytes:
        """Every byte the runner wrote to standard output and standard error."""
        return b"".join(self.session.raw) + self.session.stderr()


def replay(name: str, tmp_path: Path) -> Replayed:
    """Run the runner against fixture ``name``'s answers, in a workspace holding its files."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    provenance = load(name, "provenance.json")
    for path, content in provenance.get("workspace", {}).items():
        target = workspace / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    with FakeEndpoint(replies(name)) as fake:
        session = Session(workspace, CANARY)
        try:
            model = provenance["model"]
            session.start(fake.endpoint, dict(TEST_LIMITS), model=model, direction=DIRECTION)
            messages = session.until_result()
            session.shutdown()
        finally:
            session.kill()
        requests = len(fake.requests)
    return Replayed(session, messages, requests)
