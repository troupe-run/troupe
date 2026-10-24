"""The run/start options, checked into a frozen Options (design D10).

The rules are the published options.schema.json's, checked in code because the runner uses only
the standard library. A test compares the two on generated options, so they can't drift apart.
An option the runner doesn't define, or a value of the wrong shape, is refused, never ignored.
"""

import math
from dataclasses import dataclass
from typing import Any

PERMISSION_MODES = ("acceptEdits", "auto", "bypassPermissions", "manual", "dontAsk", "plan")
"""Claude Code 2.1.302's permission modes."""

SETTING_SOURCES = ("user", "project", "local")
"""Claude Code's setting sources."""

_OPTIONS = (
    "model",
    "maxBudgetUsd",
    "permissionMode",
    "allowedTools",
    "disallowedTools",
    "settingSources",
)


@dataclass(frozen=True)
class Options:
    """The options of one run. None is an option that wasn't set."""

    model: str | None = None
    max_budget_usd: float | None = None
    permission_mode: str | None = None
    allowed_tools: tuple[str, ...] = ()
    disallowed_tools: tuple[str, ...] = ()
    setting_sources: tuple[str, ...] = ()
    """The setting sources to load; empty when none are, which is the default."""


class OptionsError(Exception):
    """An option refused, with the code, where it is, the problem and the fix."""

    def __init__(self, code: str, where: str, problem: str, fix: str) -> None:
        super().__init__(f"{where}: {problem}")
        self.code = code
        self.where = where
        self.problem = problem
        self.fix = fix


def _invalid(where: str, problem: str, fix: str) -> OptionsError:
    return OptionsError("claude-code.invalid-options", where, problem, fix)


def _has_control(text: str) -> bool:
    return any(ord(char) < 0x20 or ord(char) == 0x7F for char in text)


def _model(value: object) -> str:
    where = "options.model"
    fix = "Give a model name, such as claude-sonnet-5-5, with no control characters."
    if not isinstance(value, str) or not value:
        raise _invalid(where, f"{value!r} isn't a model name.", fix)
    if _has_control(value):
        raise _invalid(where, "The model name has a control character.", fix)
    if value.startswith("-"):
        raise _invalid(
            where,
            f"{value!r} starts with '-', so Claude Code would read it as a flag.",
            fix,
        )
    return value


def _budget(value: object) -> float:
    where = "options.maxBudgetUsd"
    fix = "Give the most a run may spend, in US dollars, as a number above 0, such as 2.5."
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _invalid(where, f"{value!r} isn't a number.", fix)
    if not math.isfinite(value) or value <= 0:
        raise _invalid(where, f"{value!r} isn't above 0.", fix)
    return float(value)


def _choice(value: object, where: str, choices: tuple[str, ...]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise _invalid(
            where,
            f"{value!r} isn't one of {', '.join(choices)}.",
            f"Use one of: {', '.join(choices)}.",
        )
    return value


def _list(value: object, where: str) -> list[Any]:
    if not isinstance(value, list):
        raise _invalid(where, f"{value!r} isn't a list.", "Give a JSON array.")
    seen: list[object] = []
    for index, item in enumerate(value):
        if item in seen:
            raise _invalid(f"{where}[{index}]", f"{item!r} is listed twice.", "List each once.")
        seen.append(item)
    return value


def _rules(value: object, where: str) -> tuple[str, ...]:
    fix = (
        "Give each rule as a non-empty string with no control characters, such as Bash(git status)."
    )
    items = _list(value, where)
    for index, item in enumerate(items):
        if not isinstance(item, str) or not item or _has_control(item):
            raise _invalid(f"{where}[{index}]", f"{item!r} isn't a permission rule.", fix)
    return tuple(items)


def _sources(value: object) -> tuple[str, ...]:
    where = "options.settingSources"
    items = _list(value, where)
    return tuple(
        _choice(item, f"{where}[{index}]", SETTING_SOURCES) for index, item in enumerate(items)
    )


def parse_options(value: object) -> Options:
    """``value``, run/start's options, as Options. Raises OptionsError naming what's wrong."""
    if not isinstance(value, dict):
        raise _invalid(
            "options", f"{value!r} isn't an object.", "Send the options as a JSON object."
        )
    for key in value:
        if key not in _OPTIONS:
            raise OptionsError(
                "claude-code.unknown-option",
                f"options.{key}",
                f"The Claude Code runner doesn't define the option {key!r}.",
                f"Use only {', '.join(_OPTIONS)}.",
            )
    return Options(
        model=_model(value["model"]) if "model" in value else None,
        max_budget_usd=_budget(value["maxBudgetUsd"]) if "maxBudgetUsd" in value else None,
        permission_mode=(
            _choice(value["permissionMode"], "options.permissionMode", PERMISSION_MODES)
            if "permissionMode" in value
            else None
        ),
        allowed_tools=_rules(value["allowedTools"], "options.allowedTools")
        if "allowedTools" in value
        else (),
        disallowed_tools=_rules(value["disallowedTools"], "options.disallowedTools")
        if "disallowedTools" in value
        else (),
        setting_sources=_sources(value["settingSources"]) if "settingSources" in value else (),
    )


__all__ = ["PERMISSION_MODES", "SETTING_SOURCES", "Options", "OptionsError", "parse_options"]
