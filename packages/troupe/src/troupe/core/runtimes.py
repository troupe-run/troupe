"""Runtimes: the services runners talk to, and how troupe resolves one (spec: runtimes; runtimes
design D2, D3, D7).

A runtime is named once, in config, and an actor names it. Its values come from troupe's built-in
runtimes (troupe.core.defaults.RUNTIMES), then the theatre's config, then the session's
environment (``TROUPE_RUNTIME_<NAME>_ENDPOINT``, ``_MODEL`` and ``_CREDENTIAL_ENV``), each field on
its own, and each resolved value carries its source, as settings and policy do. A run's model is
the environment's, then its actor's, then the runtime's.

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

from troupe.core import defaults
from troupe.core.errors import TroupeError
from troupe.platform.processes import EnvironmentPolicy
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


@dataclass(frozen=True)
class Resolved:
    """A runtime as troupe resolved it: each value with its source. ``credential`` is the name of
    the credential's variable, never its value."""

    name: str
    endpoint: Sourced
    model: Sourced | None
    credential: Sourced | None

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
        return data

    def run_start(self) -> dict[str, Any]:
        """``run/start``'s ``runtime``."""
        return {
            "name": self.resolved.name,
            "endpoint": self.resolved.endpoint.value,
            "model": self.model.value,
            "credential": self.value is not None,
        }


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
        raise TroupeError(
            "runtime.invalid-value",
            problem=f"The runtime variable {variable} is set to {raw!r}, which isn't "
            f"{ACCEPTED[field]}.",
            fix=f"Set {variable} to {ACCEPTED[field]}, or unset it to use the runtime's own.",
            details={"variable": variable, "value": raw, "accepted": [ACCEPTED[field]]},
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
            f"{RUNTIMES}.{name}.endpoint=...",
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
    return Resolved(
        name=name, endpoint=endpoint, model=resolved["model"], credential=resolved["credential_env"]
    )


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


def for_run(
    name: str,
    actor: str,
    actor_model: str | None,
    config: Mapping[str, Any],
    env: Mapping[str, str],
) -> RunRuntime:
    """What a run of ``actor`` on the runtime ``name`` starts with, reading its credential's value
    from ``env``. Refused, before anything is recorded, with runtime.no-model,
    runtime.credential-unset, runtime.credential-too-short or runtime.insecure-endpoint. No error
    holds any part of the credential's value."""
    resolved = resolve(name, config, env)
    model = run_model(resolved, actor_model)
    if model is None:
        places = [f"actors.{actor}.model", f"{RUNTIMES}.{name}.model", env_name(name, "model")]
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
    if not value:
        raise TroupeError(
            "runtime.credential-unset",
            problem=f"The runtime {name!r} reads its credential from {variable}, which isn't set.",
            fix=f"Set {variable} in your environment to the key for {name}, or point the runtime "
            f"at another variable with {env_name(name, 'credential_env')}.",
            details={"runtime": name, "variable": variable},
        )
    if len(value.encode("utf-8")) < defaults.CREDENTIAL_MIN_BYTES:
        raise TroupeError(
            "runtime.credential-too-short",
            problem=f"The credential in {variable}, for the runtime {name!r}, is shorter than "
            f"{defaults.CREDENTIAL_MIN_BYTES} bytes, too short for troupe to keep out of what "
            "it records.",
            fix=f"Set {variable} to the real key. A service that needs no key needs no "
            f"credential: define a runtime without one.",
            details={
                "runtime": name,
                "variable": variable,
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
