"""The run/start options, checked into a frozen Options (local-model-runner design D10, D11).

The rules are the published options.schema.json's, checked in code because the runner uses only the
standard library. A test compares the two on generated options, so they can't drift apart. An
option the runner doesn't define, a missing model, or a value of the wrong shape is refused, never
ignored or replaced by a default.
"""

import math
import re
from dataclasses import dataclass
from typing import Literal

from troupe_runner_ollama.defaults import DEFAULT_ENDPOINT, MAX_TURNS, MAX_TURNS_LIMIT

THINK_LEVELS = ("low", "medium", "high")
"""The thinking levels Ollama takes for a model that has them."""

_OPTIONS = ("model", "endpoint", "maxTurns", "contextLength", "temperature", "seed", "think")

_ENDPOINT = re.compile(r"\Ahttps?://(?:\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9.-]+)(?::[0-9]{1,5})?/?\Z")
"""An endpoint: the schema's pattern, anchored as Python needs (its ``$`` would also match before a
final line feed, which the schema's control-character guard refuses)."""

Think = bool | Literal["low", "medium", "high"]


@dataclass(frozen=True)
class Options:
    """The options of one run. None is an option that wasn't set, which Ollama decides."""

    model: str
    endpoint: str = DEFAULT_ENDPOINT
    """Where requests go, without a trailing ``/``."""
    max_turns: int = MAX_TURNS
    context_length: int | None = None
    """The window the options ask for; the run's window is worked out at preflight (design D15)."""
    temperature: float | None = None
    seed: int | None = None
    think: Think | None = None


class OptionsError(Exception):
    """An option refused, with the code, where it is, the problem and the fix."""

    def __init__(self, code: str, where: str, problem: str, fix: str) -> None:
        super().__init__(f"{where}: {problem}")
        self.code = code
        self.where = where
        self.problem = problem
        self.fix = fix


def invalid(where: str, problem: str, fix: str) -> OptionsError:
    """An ``ollama.invalid-options`` refusal."""
    return OptionsError("ollama.invalid-options", where, problem, fix)


def _has_control(text: str) -> bool:
    return any(ord(char) < 0x20 or ord(char) == 0x7F for char in text)


def _model(value: object) -> str:
    where = "options.model"
    fix = "Give the model as Ollama names it, such as qwen3:4b, with no control characters."
    if not isinstance(value, str) or not value:
        raise invalid(where, f"{value!r} isn't a model name.", fix)
    if _has_control(value):
        raise invalid(where, "The model name has a control character.", fix)
    return value


def _endpoint(value: object) -> str:
    where = "options.endpoint"
    fix = (
        "Give where Ollama listens as http:// or https://, a host and an optional port, such as "
        f"{DEFAULT_ENDPOINT}, with no user name, password, path, query or fragment. Leave it unset "
        f"for {DEFAULT_ENDPOINT}."
    )
    if not isinstance(value, str):
        raise invalid(where, f"{value!r} isn't a URL.", fix)
    if "@" in value:
        # Never echo it: what's before the @ may be a password.
        raise invalid(
            where,
            "The endpoint holds a user name or password, which would be kept in config.",
            fix,
        )
    if _has_control(value):
        raise invalid(where, "The endpoint has a control character.", fix)
    if _ENDPOINT.match(value) is None:
        scheme, _, rest = value.partition("://")
        if not rest or scheme not in ("http", "https"):
            problem = f"{value!r} isn't an http or https URL."
        elif any(mark in rest for mark in "?#"):
            problem = f"{value!r} has a query or a fragment."
        elif "/" in rest.rstrip("/") or rest.endswith("//"):
            problem = f"{value!r} has a path; the runner adds /api/... itself."
        else:
            problem = f"{value!r} isn't a host and an optional port."
        raise invalid(where, problem, fix)
    return value.rstrip("/")


def _integer(value: object, where: str, minimum: int, maximum: int | None, fix: str) -> int:
    """An integer as the schema's ``integer`` reads one: a whole number, 3.0 included, never a
    boolean."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise invalid(where, f"{value!r} isn't a whole number.", fix)
    if isinstance(value, float) and not (math.isfinite(value) and value.is_integer()):
        raise invalid(where, f"{value!r} isn't a whole number.", fix)
    number = int(value)
    if number < minimum or (maximum is not None and number > maximum):
        bounds = f"at least {minimum}" if maximum is None else f"{minimum} to {maximum}"
        raise invalid(where, f"{value!r} isn't {bounds}.", fix)
    return number


def _temperature(value: object) -> float:
    where = "options.temperature"
    fix = "Give a number of 0 or more, such as 0 for the least random answers."
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise invalid(where, f"{value!r} isn't a number.", fix)
    if not math.isfinite(value) or value < 0:
        raise invalid(where, f"{value!r} isn't 0 or more.", fix)
    return float(value)


def _seed(value: object) -> int:
    where = "options.seed"
    fix = "Give a whole number, such as 42."
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise invalid(where, f"{value!r} isn't a whole number.", fix)
    if isinstance(value, float) and not (math.isfinite(value) and value.is_integer()):
        raise invalid(where, f"{value!r} isn't a whole number.", fix)
    return int(value)


def _think(value: object) -> Think:
    if isinstance(value, bool):
        return value
    if value == "low" or value == "medium" or value == "high":
        return value
    raise invalid(
        "options.think",
        f"{value!r} isn't true, false or one of {', '.join(THINK_LEVELS)}.",
        f"Use true, false, or one of: {', '.join(THINK_LEVELS)}.",
    )


def parse_options(value: object) -> Options:
    """``value``, run/start's options, as Options. Raises OptionsError naming what's wrong."""
    if not isinstance(value, dict):
        raise invalid(
            "options", f"{value!r} isn't an object.", "Send the options as a JSON object."
        )
    for key in value:
        if key not in _OPTIONS:
            raise OptionsError(
                "ollama.unknown-option",
                f"options.{key}",
                f"The Ollama runner doesn't define the option {key!r}.",
                f"Use only {', '.join(_OPTIONS)}.",
            )
    if "model" not in value:
        raise invalid(
            "options.model",
            "The options don't name a model.",
            "Set options.model to a model Ollama has pulled, such as qwen3:4b.",
        )
    return Options(
        model=_model(value["model"]),
        endpoint=_endpoint(value["endpoint"]) if "endpoint" in value else DEFAULT_ENDPOINT,
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
            1,
            None,
            "Give the context window in tokens, such as 32768, at most the model's maximum.",
        )
        if "contextLength" in value
        else None,
        temperature=_temperature(value["temperature"]) if "temperature" in value else None,
        seed=_seed(value["seed"]) if "seed" in value else None,
        think=_think(value["think"]) if "think" in value else None,
    )
