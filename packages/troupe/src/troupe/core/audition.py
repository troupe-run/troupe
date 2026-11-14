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

CLAUDE_CODE_TOOLS = ("Read", "Glob", "Grep")
"""What the Claude Code example may use besides editing: enough to read the repository. Bash isn't
allowed, though Claude Code still runs commands it classes as read-only (init-and-audition task
7.2). Editing comes from its effects, never from a tool rule (declared-effects design D8)."""

CLAUDE_CODE_EFFECTS = {"write": ["**"]}
"""What the Claude Code example may change: any file in its worktree, which reaches the theatre only
through troupe accept, after troupe diff shows it. It can't delete or move a file, so a direction
that does fails the run's audit (declared-effects design D10)."""

CHARACTER = (
    "You are a careful developer working in this repository. Read what's there before you change "
    "anything, keep each change small, and finish by saying what you changed and why.\n"
)
"""The Claude Code example's character. It is sent to the model as it is, so it holds no note to
the person: the printed output says how to change it."""

OLLAMA_AUDITION_MODEL = "qwen3.5:4b"
"""The Ollama example's model: it calls tools and thinks, is about 3.4 GB, and runs on a laptop
(local-model-runner design D13). Named here alone, so changing it is one line."""

OPENAI_AUDITION_MODEL = "gpt-6-luna"
"""The OpenAI example's model: OpenAI's cheapest current model, which calls tools over the Responses
API at its default reasoning (#290's probe, 2026-11-05). Named here alone, so changing it is one
line."""

OPENAI_AUDITION_LIMITS = {"maxTurns": 10, "maxTotalTokens": 100_000}
"""The OpenAI example's limits: enough to read a few files and write one, on a small budget
(owner, 2026-11-05; openai-style-runner design D7)."""

ANTHROPIC_AUDITION_MODEL = "claude-haiku-5-5"
"""The Anthropic example's model: Claude's cheapest current model, which calls tools over the
Messages API, as the OpenAI example names OpenAI's cheapest (anthropic-runner design D15). Named
here alone, so changing it is one line."""

ANTHROPIC_AUDITION_LIMITS = {"maxTurns": 10, "maxTotalTokens": 100_000}
"""The Anthropic example's limits, as the OpenAI example's: enough to read a few files and write
one, on a small budget (anthropic-runner design D15)."""

LM_STUDIO_AUDITION_MODEL = "google/gemma-4-e4b"
"""The LM Studio example's model: a 4B model LM Studio marks as trained for tool use, which called
tools in every round of the runner's probe (lmstudio-runner design D12, D15). Named here alone, so
changing it is one line."""

LM_STUDIO_AUDITION_LIMITS = {"maxTurns": 10, "maxTotalTokens": 100_000}
"""The LM Studio example's limits, as the OpenAI example's: enough to read a few files and write
one (lmstudio-runner design D15)."""

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
            "allowedTools": list(CLAUDE_CODE_TOOLS),
        },
        "effects": {key: list(value) for key, value in CLAUDE_CODE_EFFECTS.items()},
        # No file has to change, so whatever direction the person types can succeed (design D6).
        "expect": [],
        "character": CHARACTER,
    }


def _anthropic() -> dict[str, Any]:
    # Like the Claude Code example: it may write any file in its worktree, and no file has to
    # change. Its service is the built-in anthropic runtime, Claude's API, so its key is
    # ANTHROPIC_API_KEY's.
    return {
        "runner": "anthropic",
        "runtime": "anthropic",
        "model": ANTHROPIC_AUDITION_MODEL,
        "options": dict(ANTHROPIC_AUDITION_LIMITS),
        "effects": {key: list(value) for key, value in CLAUDE_CODE_EFFECTS.items()},
        "expect": [],
        "character": CHARACTER,
    }


def _lm_studio() -> dict[str, Any]:
    # Like the Claude Code example: it may write any file in its worktree, and no file has to
    # change. Its service is the built-in lm-studio runtime, the local LM Studio's server.
    return {
        "runner": "lm-studio",
        "runtime": "lm-studio",
        "model": LM_STUDIO_AUDITION_MODEL,
        "options": dict(LM_STUDIO_AUDITION_LIMITS),
        "effects": {key: list(value) for key, value in CLAUDE_CODE_EFFECTS.items()},
        "expect": [],
        "character": CHARACTER,
    }


def _ollama() -> dict[str, Any]:
    # Like the Claude Code example: it may write any file in its worktree, and no file has to
    # change. Its service is the built-in ollama runtime, the local Ollama, and it takes no
    # options (ollama-uses-runtime design D6).
    return {
        "runner": "ollama",
        "runtime": "ollama",
        "model": OLLAMA_AUDITION_MODEL,
        "effects": {key: list(value) for key, value in CLAUDE_CODE_EFFECTS.items()},
        "expect": [],
        "character": CHARACTER,
    }


def _openai() -> dict[str, Any]:
    # Like the Claude Code example: it may write any file in its worktree, and no file has to
    # change. Its service is the built-in openai runtime, so its key is OPENAI_API_KEY's.
    return {
        "runner": "openai",
        "runtime": "openai",
        "model": OPENAI_AUDITION_MODEL,
        "options": dict(OPENAI_AUDITION_LIMITS),
        "effects": {key: list(value) for key, value in CLAUDE_CODE_EFFECTS.items()},
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
    return {
        "runner": "scripted",
        "options": {"script": {"steps": list(steps)}},
        "effects": {"write": [FILE]},
        "expect": [FILE],
    }


AUDITIONS: Mapping[str, Callable[[], dict[str, Any]]] = {
    "anthropic": _anthropic,
    "claude-code": _claude_code,
    "lm-studio": _lm_studio,
    "ollama": _ollama,
    "openai": _openai,
    "scripted": _scripted,
}
"""Each runner's example actor, by the runner's name."""


def audition(runner: str | None) -> Audition:
    """The example actor for ``runner`` (DEFAULT_RUNNER when None). A runner troupe doesn't know is
    runner.unknown, naming the ones it does, never the default; one that isn't installed is
    runner.not-installed, naming its extra (runner-extras design D8)."""
    name = DEFAULT_RUNNER if runner is None else runner
    interim.installed_runner(name)
    build = AUDITIONS.get(name)
    if build is None:
        raise TroupeError(
            "internal.unexpected",
            problem=f"troupe knows the runner {name!r} but has no audition for it.",
            fix="This is a bug in troupe: add the runner's audition to troupe.core.audition.",
        )
    return Audition(name, build(), DIRECTION)
