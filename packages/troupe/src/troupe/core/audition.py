"""The example actor troupe init --audition defines (spec: config; init-and-audition design D6).

What the example actor holds is decided here and nowhere else: its name, and for each runner troupe
knows, the actor's values and the direction the printed next step suggests. Every runner in
troupe.core.interim has an audition (a test checks), so a new runner can't quietly fall through to
another runner's example.

The values are built when asked for, not at import: the scripted runner's ``init`` event reports
the installed runner's version, so the event it plays is true.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from importlib.metadata import version
from typing import Any

from troupe.core import interim
from troupe.core.config.kinds import ACTORS
from troupe.core.errors import TroupeError

ACTOR = "lead"
"""The example actor's name, whatever its runner (design D6)."""

DEFAULT_RUNNER = "claude-code"
"""The runner an audition uses when none is named (#232: Claude Code by default)."""

FILE = "AUDITION.md"
"""The file the example direction asks for, and the scripted example writes and checks."""

DIRECTION = f"Write {FILE}: a short note on what this repository holds, for someone new to it."
"""The direction the printed perform step suggests, for every runner."""

CLAUDE_CODE_MAX_BUDGET_USD = 1
"""The Claude Code example's budget per run, in US dollars: small, and the figure the first-run page
already used."""

CLAUDE_CODE_TOOLS = ("Read", "Write", "Edit", "Glob", "Grep")
"""What the Claude Code example may use: enough to read the repository and write a file. Bash isn't
allowed, though Claude Code still runs commands it classes as read-only (init-and-audition task
7.2)."""

CHARACTER = (
    "You are a careful developer working in this repository. Read what's there before you change "
    "anything, keep each change small, and finish by saying what you changed and why.\n"
)
"""The Claude Code example's character. It is sent to the model as it is, so it holds no note to
the person: the printed output says where to edit it."""

SCRIPTED_CONTENT = (
    "# Audition\n\nWritten by troupe's scripted runner, which plays a script instead of running an "
    "agent. Swap the runner for claude-code to run a real one.\n"
)
"""What the scripted example writes to FILE."""


@dataclass(frozen=True)
class Audition:
    """An example actor: its runner, its values under ``actors.<ACTOR>``, and a direction."""

    runner: str
    actor: Mapping[str, Any]
    direction: str

    def operations(self) -> list[tuple[tuple[str, ...], object]]:
        """The actor as config-set operations: one for each value, a group's values each on its
        own, since an object in config is a group (spec: config)."""
        found: list[tuple[tuple[str, ...], object]] = []
        _leaves((ACTORS, ACTOR), self.actor, found)
        return found


def _leaves(
    base: tuple[str, ...], value: object, found: list[tuple[tuple[str, ...], object]]
) -> None:
    if isinstance(value, Mapping):
        for key, inner in value.items():
            _leaves((*base, key), inner, found)
    else:
        found.append((base, value))


def _claude_code() -> dict[str, Any]:
    return {
        "runner": "claude-code",
        "options": {
            "maxBudgetUsd": CLAUDE_CODE_MAX_BUDGET_USD,
            "permissionMode": "acceptEdits",
            "allowedTools": list(CLAUDE_CODE_TOOLS),
        },
        # No effect check, so whatever direction the person types can succeed (design D6).
        "expect": [],
        "character": CHARACTER,
    }


def _scripted() -> dict[str, Any]:
    runner = {"name": "scripted", "version": version(interim.RUNNERS["scripted"].package)}
    steps: Sequence[Mapping[str, Any]] = (
        {"event": {"type": "init", "runner": runner, "tools": ["Write"]}},
        {"writeFile": {"path": FILE, "content": SCRIPTED_CONTENT}},
        {"event": {"type": "result", "status": "ok", "message": f"wrote {FILE}"}},
    )
    # The effect check is shown where it can't fail by chance; no character, since the scripted
    # runner doesn't read one (design D6).
    return {"runner": "scripted", "options": {"script": {"steps": list(steps)}}, "expect": [FILE]}


AUDITIONS: Mapping[str, Callable[[], dict[str, Any]]] = {
    "claude-code": _claude_code,
    "scripted": _scripted,
}
"""Each runner's example actor, by the runner's name."""


def audition(runner: str | None) -> Audition:
    """The example actor for ``runner`` (DEFAULT_RUNNER when None). A runner troupe doesn't know is
    runner.unknown, naming the ones it does, never the default."""
    name = DEFAULT_RUNNER if runner is None else runner
    interim.runner(name)
    build = AUDITIONS.get(name)
    if build is None:
        raise TroupeError(
            "internal.unexpected",
            problem=f"troupe knows the runner {name!r} but has no audition for it.",
            fix="This is a bug in troupe: add the runner's audition to troupe.core.audition.",
        )
    return Audition(name, build(), DIRECTION)
