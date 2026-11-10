"""The run/start options, checked into frozen Options (lmstudio-runner design D5).

The rules are the published options.schema.json's, checked in code. A test compares the two on
generated options, so they can't drift apart. An option the runner doesn't define, or a value of the
wrong shape, is refused, never ignored. The service (endpoint, model) comes from the run's runtime,
so naming it here is an unknown option like any other.
"""

import math
from dataclasses import dataclass

from troupe_runner_lm_studio.defaults import (
    DEFAULT_CONTEXT_LENGTH,
    DEFAULT_MAX_TOTAL_TOKENS,
    DEFAULT_MAX_TURNS,
)

_OPTIONS = ("maxTurns", "maxTotalTokens", "contextLength", "temperature")


@dataclass(frozen=True)
class Options:
    """The options of one run, with the runner's defaults filled in where they weren't set."""

    max_turns: int = DEFAULT_MAX_TURNS
    max_total_tokens: int = DEFAULT_MAX_TOTAL_TOKENS
    context_length: int = DEFAULT_CONTEXT_LENGTH
    temperature: float | None = None
    """None: the model's own default."""


class OptionsError(Exception):
    """An option refused, with the code, where it is, the problem and the fix."""

    def __init__(self, code: str, where: str, problem: str, fix: str) -> None:
        super().__init__(f"{where}: {problem}")
        self.code = code
        self.where = where
        self.problem = problem
        self.fix = fix


def _positive(value: object, name: str, what: str) -> int:
    where = f"options.{name}"
    # JSON Schema's integer is any number with no fraction, 1.0 included, and config checks the
    # options against the published schema: what it accepts, the runner must too.
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise OptionsError(
            "lm-studio.invalid-options",
            where,
            f"{value!r} isn't a whole number of {what} above 0.",
            f"Give {name} as a whole number of 1 or more, such as 5.",
        )
    return value


def _temperature(value: object) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(value)
        or not 0 <= value <= 1
    ):
        raise OptionsError(
            "lm-studio.invalid-options",
            "options.temperature",
            f"{value!r} isn't a number from 0 to 1.",
            "Give temperature as a number from 0 to 1, such as 0.2, or leave it out for the "
            "model's own default.",
        )
    return float(value)


def parse_options(value: object) -> Options:
    """``value``, run/start's options, as Options. Raises OptionsError naming what's wrong."""
    if not isinstance(value, dict):
        raise OptionsError(
            "lm-studio.invalid-options",
            "options",
            f"{value!r} isn't an object.",
            "Send the options as a JSON object.",
        )
    for key in value:
        if key not in _OPTIONS:
            raise OptionsError(
                "lm-studio.unknown-option",
                f"options.{key}",
                f"The LM Studio runner doesn't define the option {key!r}.",
                f"Use only {', '.join(_OPTIONS)}. The endpoint and model come from the actor's "
                "runtime, not its options.",
            )
    return Options(
        max_turns=_positive(value["maxTurns"], "maxTurns", "rounds")
        if "maxTurns" in value
        else DEFAULT_MAX_TURNS,
        max_total_tokens=_positive(value["maxTotalTokens"], "maxTotalTokens", "tokens")
        if "maxTotalTokens" in value
        else DEFAULT_MAX_TOTAL_TOKENS,
        context_length=_positive(value["contextLength"], "contextLength", "tokens")
        if "contextLength" in value
        else DEFAULT_CONTEXT_LENGTH,
        temperature=_temperature(value["temperature"]) if "temperature" in value else None,
    )


__all__ = ["Options", "OptionsError", "parse_options"]
