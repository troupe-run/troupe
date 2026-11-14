"""The run/start options, checked into a frozen Options (spec: mistralrs-runner, "The runner's
options are closed").

The rules are the published options.schema.json's, checked in code. A test compares the two on
generated options, so they can't drift apart. An option the runner doesn't define, or a value of
the wrong shape, is refused, never ignored or replaced by a default. The model isn't an option: it
is the run's runtime's (runtime.py; in-process-runner design D5).
"""

import math
from dataclasses import dataclass

from troupe_runner_mistralrs.defaults import (
    CONTEXT_LENGTH_MAX,
    CONTEXT_LENGTH_MIN,
    MAX_TURNS,
    MAX_TURNS_LIMIT,
)

OPTIONS = ("maxTurns", "contextLength", "temperature", "seed", "think")

TEMPERATURE_MAX = 2.0
"""The largest temperature the options may set."""

SEED_MAX = 2**64 - 1
"""The largest seed: the engine takes an unsigned 64-bit one."""


@dataclass(frozen=True)
class Options:
    """The options of one run. None is an option that wasn't set, which the model decides."""

    max_turns: int = MAX_TURNS
    context_length: int | None = None
    """The window the options ask for; the run's window is worked out once the model is loaded
    (design D7)."""
    temperature: float | None = None
    seed: int | None = None
    think: bool | None = None


class OptionsError(Exception):
    """An option refused, with the code, where it is, the problem and the fix."""

    def __init__(self, code: str, where: str, problem: str, fix: str) -> None:
        super().__init__(f"{where}: {problem}")
        self.code = code
        self.where = where
        self.problem = problem
        self.fix = fix


def invalid(where: str, problem: str, fix: str) -> OptionsError:
    """A ``mistralrs.invalid-options`` refusal."""
    return OptionsError("mistralrs.invalid-options", where, problem, fix)


def _integer(value: object, where: str, minimum: int, maximum: int, fix: str) -> int:
    """An integer as the schema's ``integer`` reads one: a whole number, 3.0 included, never a
    boolean."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise invalid(where, f"{value!r} isn't a whole number.", fix)
    if isinstance(value, float) and not (math.isfinite(value) and value.is_integer()):
        raise invalid(where, f"{value!r} isn't a whole number.", fix)
    number = int(value)
    if number < minimum or number > maximum:
        raise invalid(where, f"{value!r} isn't {minimum} to {maximum}.", fix)
    return number


def _temperature(value: object) -> float:
    where = "options.temperature"
    fix = f"Give a number from 0 to {TEMPERATURE_MAX:g}, such as 0 for the least random answers."
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise invalid(where, f"{value!r} isn't a number.", fix)
    if not math.isfinite(value) or value < 0 or value > TEMPERATURE_MAX:
        raise invalid(where, f"{value!r} isn't 0 to {TEMPERATURE_MAX:g}.", fix)
    return float(value)


def _think(value: object) -> bool:
    if isinstance(value, bool):
        return value
    raise invalid("options.think", f"{value!r} isn't true or false.", "Use true or false.")


def parse_options(value: object) -> Options:
    """``value``, run/start's options, as Options. Raises OptionsError naming what's wrong."""
    if not isinstance(value, dict):
        raise invalid(
            "options", f"{value!r} isn't an object.", "Send the options as a JSON object."
        )
    for key in value:
        if key not in OPTIONS:
            model = (
                " The model is the run's runtime's: set TROUPE_RUNTIME_MISTRALRS_MODEL, or the "
                "actor's model, to the absolute path of a GGUF file."
                if key == "model"
                else ""
            )
            raise OptionsError(
                "mistralrs.unknown-option",
                f"options.{key}",
                f"The mistralrs runner doesn't define the option {key!r}.{model}",
                f"Use only {', '.join(OPTIONS)}.",
            )
    return Options(
        max_turns=_integer(
            value["maxTurns"],
            "options.maxTurns",
            1,
            MAX_TURNS_LIMIT,
            f"Give how many requests a run may make, 1 to {MAX_TURNS_LIMIT}. Unset: {MAX_TURNS}.",
        )
        if "maxTurns" in value
        else MAX_TURNS,
        context_length=_integer(
            value["contextLength"],
            "options.contextLength",
            CONTEXT_LENGTH_MIN,
            CONTEXT_LENGTH_MAX,
            f"Give the context window in tokens, {CONTEXT_LENGTH_MIN} to {CONTEXT_LENGTH_MAX}, "
            "such as 32768, at most the model's own length.",
        )
        if "contextLength" in value
        else None,
        temperature=_temperature(value["temperature"]) if "temperature" in value else None,
        seed=_integer(
            value["seed"], "options.seed", 0, SEED_MAX, "Give a whole number, such as 42."
        )
        if "seed" in value
        else None,
        think=_think(value["think"]) if "think" in value else None,
    )
