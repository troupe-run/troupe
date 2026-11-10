"""Runtimes: the services runners talk to, and how troupe resolves one (spec: runtimes; runtimes
design D2, D3, D7).

A runtime is named once, in config, and an actor names it. Its values come from troupe's built-in
runtimes (troupe.core.defaults.RUNTIMES), then the theatre's config, then the session's
environment (``TROUPE_RUNTIME_<NAME>_ENDPOINT``, ``_MODEL`` and ``_CREDENTIAL_ENV``), each field on
its own, and each resolved value carries its source, as settings and policy do. A run's model is
the environment's, then its actor's, then the runtime's.

A runtime may price its models (``prices``, by model name). A run's price is the price for its
model, matched exactly, from the theatre's config only: troupe has no built-in prices and no
variable sets one (spec: runtimes, "A run's price is the price of its model"; estimated-cost design
D3, D6). It goes to the runner in ``run/start``, the only price a runner may estimate a cost from.

A credential is only ever a reference: the name of the variable that holds it. Its value is read
from the session's environment when a run starts (``for_run``), never written to config, and
masked in everything troupe keeps from the run (troupe.core.masking). A variable that is set but
malformed is an error, never a fall-through; an unset or empty one is absent.

Accepted for now (owner, 2026-11-04, on #278; design D7): the theatre's config, which is
committed, may choose both the endpoint a credential goes to and which variable is sent. Policy
will limit both. What troupe refuses regardless is a credential over plain HTTP to a host that
isn't a literal loopback address, and one too short to mask.
"""

import ipaddress
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

from troupe.core import defaults, interim
from troupe.core.config_paths import shown
from troupe.core.errors import TroupeError
from troupe.platform.processes import EnvironmentPolicy
from troupe_plugin_sdk.credential import well_formed
from troupe_plugin_sdk.runner import ENDPOINT_PATTERN, MODEL_PATTERN

RUNTIMES = "runtimes"
ENV_PREFIX = "TROUPE_RUNTIME_"
FIELDS = ("endpoint", "model", "credential_env")
"""The fields the environment can set, by the suffix of their variable's name in lower case."""

VARIABLE_PATTERN = re.compile(r"\A(?![Tt][Rr][Oo][Uu][Pp][Ee]_)[A-Za-z_][A-Za-z0-9_]{0,255}\Z")
"""A credential's variable: letters, digits and _, not starting with a digit or with TROUPE_ in
any case (protocol/schemas/runtime.schema.json)."""

ACCEPTED = {
    "endpoint": "an http or https URL with a host, and no user info, query or fragment",
    "model": "a model's name: 1 to 256 characters, none of them a control character",
    "credential_env": "an environment variable's name (letters, digits and _, not starting with a "
    "digit), not one of troupe's own (TROUPE_...)",
}
PATTERNS = {
    "endpoint": ENDPOINT_PATTERN,
    "model": MODEL_PATTERN,
    "credential_env": VARIABLE_PATTERN,
}

Source = Literal["default", "theatre", "env", "actor"]


@dataclass(frozen=True)
class Sourced:
    """A resolved value, and where it came from."""

    value: str
    source: Source

    def to_data(self) -> dict[str, str]:
        return {"value": self.value, "source": self.source}


PRICES = "prices"


@dataclass(frozen=True)
class Price:
    """A model's price as config holds it (runtime.schema.json#/$defs/price), and where it came
    from: always the theatre's config, since troupe has no built-in prices."""

    value: Mapping[str, float]
    source: Source = "theatre"

    def to_data(self) -> dict[str, Any]:
        return {"value": dict(self.value), "source": self.source}


def model_price(theatre: Mapping[str, Any], model: str | None) -> Price | None:
    """The price ``theatre`` (one runtime's config) holds for ``model``, matched exactly, or None.
    Config has been checked, so each price has the schema's shape."""
    prices = theatre.get(PRICES)
    if model is None or not isinstance(prices, Mapping):
        return None
    price = prices.get(model)
    return Price(price) if isinstance(price, Mapping) else None


@dataclass(frozen=True)
class Resolved:
    """A runtime as troupe resolved it: each value with its source. ``credential`` is the name of
    the credential's variable, never its value."""

    name: str
    endpoint: Sourced
    model: Sourced | None
    credential: Sourced | None
    prices: Mapping[str, Any]
    """The runtime's prices in the theatre's config, by model name; empty when it has none."""

    def price(self, model: Sourced | None) -> Price | None:
        """The price of ``model`` on this runtime, or None."""
        return model_price({PRICES: self.prices}, model.value if model is not None else None)

    def to_data(self, env: Mapping[str, str]) -> dict[str, Any]:
        """The protocol's resolved runtime (runtime.schema.json#/$defs/resolved), saying whether
        the credential's variable is set in ``env``. Never the credential's value."""
        data: dict[str, Any] = {"name": self.name, "endpoint": self.endpoint.to_data()}
        if self.model is not None:
            data["model"] = self.model.to_data()
        if self.credential is not None:
            data["credential"] = {
                "env": self.credential.to_data(),
                "set": bool(read_variable(env, self.credential.value)),
            }
        price = self.price(self.model)
        if price is not None:
            data["price"] = price.to_data()
        return data


@dataclass(frozen=True)
class RunRuntime:
    """What a run on a runtime starts with: the resolved runtime, its model, and its credential's
    value when it has one. ``value`` is never written anywhere; troupe masks it in what it keeps."""

    resolved: Resolved
    model: Sourced
    value: str | None

    def to_data(self) -> dict[str, Any]:
        """The runtime the run's start records: every value with its source, never the value."""
        data: dict[str, Any] = {
            "name": self.resolved.name,
            "endpoint": self.resolved.endpoint.to_data(),
            "model": self.model.to_data(),
        }
        if self.resolved.credential is not None:
            data["credential"] = {"env": self.resolved.credential.to_data(), "set": True}
        price = self.resolved.price(self.model)
        if price is not None:
            data["price"] = price.to_data()
        return data

    def run_start(self) -> dict[str, Any]:
        """``run/start``'s ``runtime``, with the run's model's price when it has one."""
        data: dict[str, Any] = {
            "name": self.resolved.name,
            "endpoint": self.resolved.endpoint.value,
            "model": self.model.value,
            "credential": self.value is not None,
        }
        price = self.resolved.price(self.model)
        if price is not None:
            data["price"] = dict(price.value)
        return data


def env_name(runtime: str, field: str) -> str:
    """The variable that sets ``field`` of ``runtime``: ``TROUPE_RUNTIME_OPENAI_ENDPOINT``."""
    return f"{ENV_PREFIX}{runtime.upper().replace('-', '_')}_{field.upper()}"


def configured(config: Mapping[str, Any]) -> Mapping[str, Any]:
    """The runtimes the theatre's config holds."""
    node = config.get(RUNTIMES, {})
    return node if isinstance(node, Mapping) else {}


def names(config: Mapping[str, Any]) -> list[str]:
    """Every runtime there is: troupe's built-in ones and those in config, sorted."""
    return sorted(set(defaults.RUNTIMES) | set(configured(config)))


def read_variable(env: Mapping[str, str], name: str) -> str:
    """The value of the variable ``name`` in ``env``, matched as the platform matches names (so
    case-insensitively on Windows), or the empty string when it isn't set."""
    policy = EnvironmentPolicy(names=frozenset({name}))
    found = [value for key, value in env.items() if policy.selects(key)]
    return next((value for value in found if value), "")


def _from_env(runtime: str, field: str, env: Mapping[str, str]) -> str | None:
    variable = env_name(runtime, field)
    raw = env.get(variable, "")
    if raw == "":
        return None
    if not PATTERNS[field].match(raw):
        # Never the value: a key put here by mistake, or an endpoint's password, would be
        # printed and recorded (#298). The person can read it from their own environment.
        raise TroupeError(
            "runtime.invalid-value",
            problem=f"The runtime variable {variable} is set to something that isn't "
            f"{ACCEPTED[field]}.",
            fix=f"Set {variable} to {ACCEPTED[field]}, or unset it to use the runtime's own.",
            details={"variable": variable, "accepted": [ACCEPTED[field]]},
        )
    return raw


def _field(
    name: str, field: str, built_in: Mapping[str, Any], theatre: Mapping[str, Any]
) -> Sourced | None:
    if field == "credential_env":
        theatre_value = (theatre.get("credential") or {}).get("env")
        built_in_value = (built_in.get("credential") or {}).get("env")
    else:
        theatre_value, built_in_value = theatre.get(field), built_in.get(field)
    if isinstance(theatre_value, str):
        return Sourced(theatre_value, "theatre")
    if isinstance(built_in_value, str):
        return Sourced(built_in_value, "default")
    return None


def resolve(name: str, config: Mapping[str, Any], env: Mapping[str, str]) -> Resolved:
    """The runtime ``name`` as troupe resolves it now: defaults, then the theatre's config, then
    ``env``. Config has been checked, so a runtime that isn't built in has an endpoint. Raises
    runtime.invalid-value for a malformed variable, and config.invalid for a name no runtime has.
    """
    built_in: Mapping[str, Any] = defaults.RUNTIMES.get(name, {})
    theatre: Mapping[str, Any] = configured(config).get(name, {})
    if not built_in and not theatre:
        known = ", ".join(names(config))
        raise TroupeError(
            "config.invalid",
            problem=f"There's no runtime named {name!r} (there are: {known}).",
            fix=f"Use one of: {known}, or define it with troupe config set "
            f"{shown((RUNTIMES, name, 'endpoint'))}=...",
            details={"path": [RUNTIMES, name], "rule": "there's no such runtime"},
        )
    resolved: dict[str, Sourced | None] = {}
    for field in FIELDS:
        from_env = _from_env(name, field, env)
        resolved[field] = (
            Sourced(from_env, "env")
            if from_env is not None
            else _field(name, field, built_in, theatre)
        )
    endpoint = resolved["endpoint"]
    if endpoint is None:  # config's check refuses a runtime with no endpoint
        msg = f"the runtime {name!r} has no endpoint"
        raise RuntimeError(msg)
    prices = theatre.get(PRICES)
    return Resolved(
        name=name,
        endpoint=endpoint,
        model=resolved["model"],
        credential=resolved["credential_env"],
        prices=prices if isinstance(prices, Mapping) else {},
    )


Reason = Literal["credential", "endpoint-path", "endpoint-no-path"]
"""Why a runtime doesn't fit a runner: it has a credential the runner never sends, its endpoint has
a path the runner can't use, or it has none where the runner needs one (runtime-checks design
D2)."""


def has_path(endpoint: str) -> bool:
    """Whether ``endpoint`` has a path: anything after the host and port but a lone ``/``."""
    return urlsplit(endpoint).path.strip("/") != ""


def unfit(fit: interim.RuntimeFit, endpoint: str, has_credential: bool) -> list[Reason]:
    """Why a runtime whose endpoint is ``endpoint``, with a credential or not, doesn't fit a runner
    whose fit is ``fit``: empty when it fits. The one rule config and perform judge fit by
    (runtime-checks design D2)."""
    reasons: list[Reason] = []
    if has_credential and not fit.credential:
        reasons.append("credential")
    if fit.path == "none" and has_path(endpoint):
        reasons.append("endpoint-path")
    if fit.path == "required" and not has_path(endpoint):
        reasons.append("endpoint-no-path")
    return reasons


def unfit_words(runner: str, runtime: str, reason: Reason) -> str:
    """``reason`` in words, naming the runner and the runtime."""
    if reason == "credential":
        return f"the {runner} runner sends no credential, and the runtime {runtime!r} has one"
    if reason == "endpoint-path":
        return (
            f"the {runner} runner needs an endpoint with no path, and the runtime {runtime!r} has "
            "one with a path"
        )
    return (
        f"the {runner} runner needs an endpoint with a path, such as /v1, and the runtime "
        f"{runtime!r} has one without"
    )


def fitting(fit: interim.RuntimeFit) -> str:
    """What a runtime that fits looks like, in words, for a fix that defines one."""
    parts = {
        "none": "an endpoint with no path (such as http://127.0.0.1:11434)",
        "required": "an endpoint with a path (such as https://host/v1)",
        "any": "an endpoint",
    }
    words = parts[fit.path]
    return words + ("" if fit.credential else " and no credential")


def as_configured(config: Mapping[str, Any]) -> dict[str, "Resolved | None"]:
    """Every runtime there is, each as its built-in and theatre values make it, with no
    environment: how config judges fit, since config is shared and the environment is one
    person's (runtime-checks design D3). None for a runtime config can't resolve, whose own
    problems config reports."""
    shapes: dict[str, Resolved | None] = {}
    for name in names(config):
        try:
            shapes[name] = resolve(name, config, {})
        except (RuntimeError, TroupeError):
            shapes[name] = None
    return shapes


def run_model(resolved: Resolved, actor_model: str | None) -> Sourced | None:
    """A run's model: the environment's, then the actor's, then the runtime's in config (spec:
    runtimes, "The run's model comes from the environment, the actor, then the runtime")."""
    if resolved.model is not None and resolved.model.source == "env":
        return resolved.model
    if actor_model is not None:
        return Sourced(actor_model, "actor")
    return resolved.model


def is_loopback(endpoint: str) -> bool:
    """Whether ``endpoint``'s host is ``localhost`` or a literal loopback address. No name is
    looked up: a lookup could be made to answer anything."""
    host = (urlsplit(endpoint).hostname or "").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _naming(runtime: str, credential: Sourced) -> tuple[str, dict[str, str]]:
    """How a credential refusal names the credential's variable: its words, and its detail
    (design D6). A name from the environment is never repeated, since a key can pass for one:
    the refusal names the TROUPE_RUNTIME_ variable that held it, where the person can read it. A
    name from config or a built-in is named as it is."""
    if credential.source == "env":
        named_by = env_name(runtime, "credential_env")
        return f"the variable {named_by} names", {"namedBy": named_by}
    return credential.value, {"variable": credential.value}


def _came_from(runtime: str, field: str, value: Sourced) -> str:
    """Where a value that made a runtime unfit came from: the variable, the config path, or
    ``default``. Never the value, which for a credential's variable may be a key (#298 D6)."""
    if value.source == "env":
        return env_name(runtime, field)
    if value.source == "theatre":
        return shown((RUNTIMES, runtime, *field.split("_")))
    return "default"


def refuse_unfit(
    resolved: Resolved, runner: str, actor: str, config: Mapping[str, Any], env: Mapping[str, str]
) -> None:
    """Refuse with runtime.unfit when ``resolved``, the environment applied, doesn't fit
    ``runner``: the rule config judges by, applied to what the run would really use
    (runtime-checks design D4). Names where each value came from and the runtimes that fit, judged
    the same way, leaving out any whose variables are malformed."""
    fit = interim.runner(runner).fit
    reasons = unfit(fit, resolved.endpoint.value, resolved.credential is not None)
    if not reasons:
        return
    came_from: dict[str, str] = {}
    if "credential" in reasons and resolved.credential is not None:
        came_from["credential"] = _came_from(resolved.name, "credential_env", resolved.credential)
    if "endpoint-path" in reasons or "endpoint-no-path" in reasons:
        came_from["endpoint"] = _came_from(resolved.name, "endpoint", resolved.endpoint)
    fits: list[str] = []
    for other in names(config):
        try:
            candidate = resolve(other, config, env)
        except (RuntimeError, TroupeError):
            continue
        if not unfit(fit, candidate.endpoint.value, candidate.credential is not None):
            fits.append(other)
    why = "; and ".join(unfit_words(runner, resolved.name, reason) for reason in reasons)
    where = ", ".join(f"its {key} from {place}" for key, place in came_from.items())
    change = " or ".join(
        f"unset {place}" if place.startswith(ENV_PREFIX) else f"change {place}"
        for place in came_from.values()
        if place != "default"
    )
    fix = (
        (f"{change[0].upper()}{change[1:]}, or set " if change else "Set ")
        + f"{shown(('actors', actor, 'runtime'))} to "
        + (f"one that fits: {', '.join(fits)}." if fits else f"a runtime with {fitting(fit)}.")
    )
    raise TroupeError(
        "runtime.unfit",
        problem=f"{actor!r} can't run on the runtime {resolved.name!r} as it resolves here "
        f"({where}): {why}.",
        fix=fix,
        details={
            "actor": actor,
            "runner": runner,
            "runtime": resolved.name,
            "reasons": list(reasons),
            "from": came_from,
            "fits": fits,
        },
    )


def for_run(
    name: str,
    actor: str,
    actor_model: str | None,
    config: Mapping[str, Any],
    env: Mapping[str, str],
    *,
    runner: str | None = None,
) -> RunRuntime:
    """What a run of ``actor`` on the runtime ``name`` starts with, reading its credential's value
    from ``env``. With ``runner``, the runtime as resolved must fit it, judged before its model
    and credential (runtime.unfit). Refused, before anything is recorded, with runtime.unfit,
    runtime.no-model,
    runtime.credential-unset, runtime.credential-malformed, runtime.credential-too-short or
    runtime.insecure-endpoint. No error holds any part of the credential's value."""
    resolved = resolve(name, config, env)
    if runner is not None:
        refuse_unfit(resolved, runner, actor, config, env)
    model = run_model(resolved, actor_model)
    if model is None:
        places = [
            shown(("actors", actor, "model")),
            shown((RUNTIMES, name, "model")),
            env_name(name, "model"),
        ]
        raise TroupeError(
            "runtime.no-model",
            problem=f"Nothing sets the model for {actor!r}'s runs on the runtime {name!r}.",
            fix=f"Set one: troupe config set {places[0]}=<model>, or {places[1]}=<model> for "
            f"every actor on {name}, or {places[2]} in your environment.",
            details={"runtime": name, "actor": actor, "places": places},
        )
    if resolved.credential is None:
        return RunRuntime(resolved, model, None)
    variable = resolved.credential.value
    value = read_variable(env, variable)
    where, naming = _naming(name, resolved.credential)
    if not value:
        raise TroupeError(
            "runtime.credential-unset",
            problem=f"The runtime {name!r} reads its credential from {where}, which isn't set.",
            fix=(
                f"Set {env_name(name, 'credential_env')} to the name of the variable that holds "
                f"the key for {name}, not the key itself, and set that variable, or unset "
                f"{env_name(name, 'credential_env')} to use the runtime's own."
                if "namedBy" in naming
                else f"Set {where} in your environment to the key for {name}, or point the "
                f"runtime at another variable with {env_name(name, 'credential_env')}."
            ),
            details={"runtime": name, **naming},
        )
    if not well_formed(value):  # before too short: "abc\n" is likelier a file's line ending (D4)
        raise TroupeError(
            "runtime.credential-malformed",
            problem=f"The credential in {where}, for the runtime {name!r}, holds a character a "
            "request header can't carry, such as a space, a line ending left from the file it was "
            "read from, or a letter outside ASCII.",
            fix=f"Set {where} to the key alone: only visible ASCII characters, with no spaces or "
            "line endings.",
            details={"runtime": name, **naming},
        )
    if len(value.encode("utf-8")) < defaults.CREDENTIAL_MIN_BYTES:
        raise TroupeError(
            "runtime.credential-too-short",
            problem=f"The credential in {where}, for the runtime {name!r}, is shorter than "
            f"{defaults.CREDENTIAL_MIN_BYTES} bytes, too short for troupe to keep out of what "
            "it records.",
            fix=f"Set {where} to the real key. A service that needs no key needs no "
            f"credential: define a runtime without one.",
            details={
                "runtime": name,
                **naming,
                "minimumBytes": defaults.CREDENTIAL_MIN_BYTES,
            },
        )
    endpoint = resolved.endpoint.value
    if urlsplit(endpoint).scheme == "http" and not is_loopback(endpoint):
        raise TroupeError(
            "runtime.insecure-endpoint",
            problem=f"The runtime {name!r} would send its credential over plain HTTP to "
            f"{endpoint}, which isn't this machine.",
            fix=f"Use an https endpoint for {name}, or a loopback address (localhost, "
            "127.0.0.1, [::1]).",
            details={"runtime": name, "endpoint": endpoint},
        )
    return RunRuntime(resolved, model, value)
