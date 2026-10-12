"""Policy: the one seam through which policy settings are read (spec: policy;
perform-status-logs design D6).

Nothing else in troupe reads a policy value (#8). Each setting has its default in
troupe.core.defaults, and each value read carries the source it came from, because lineage records
what allowed an unenforced run. Until config brings policy files and #8's combinators, the only
source above the default is the environment: ``TROUPE_POLICY_`` and the setting's name in capitals.
An unset or empty variable is absent and falls through to the default; anything else that isn't
an accepted value is an error, never a quiet default. Policy never comes from a request: it is read
from the session's environment.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from troupe.core import defaults
from troupe.core.errors import TroupeError

ENV_PREFIX = "TROUPE_POLICY_"
ALLOW_UNENFORCED_LOCAL_STAGE = "allow_unenforced_local_stage"

PolicySource = Literal["default", "env"]
BOOLEANS = {"true": True, "false": False}


@dataclass(frozen=True)
class PolicyFlag:
    """A boolean policy setting's value, and where it came from."""

    setting: str
    value: bool
    source: PolicySource


@dataclass(frozen=True)
class Policy:
    """Every policy setting troupe has, read once for a command."""

    allow_unenforced_local_stage: PolicyFlag


def env_name(setting: str) -> str:
    """The environment variable that sets ``setting``."""
    return ENV_PREFIX + setting.upper()


def read_policy(env: Mapping[str, str]) -> Policy:
    """The policy in effect for a command run with ``env``. Raises policy.invalid-value for a
    malformed value."""
    return Policy(
        allow_unenforced_local_stage=_flag(
            ALLOW_UNENFORCED_LOCAL_STAGE, defaults.ALLOW_UNENFORCED_LOCAL_STAGE, env
        )
    )


def _flag(setting: str, default: bool, env: Mapping[str, str]) -> PolicyFlag:
    name = env_name(setting)
    raw = env.get(name, "")
    if raw == "":
        return PolicyFlag(setting, default, "default")
    if raw not in BOOLEANS:
        raise TroupeError(
            "policy.invalid-value",
            problem=f"The policy variable {name} is set to {raw!r}, which isn't true or false.",
            fix=f"Set {name} to exactly true or false, or unset it to use the default "
            f"({str(default).lower()}).",
            details={"variable": name, "value": raw, "accepted": sorted(BOOLEANS)},
        )
    return PolicyFlag(setting, BOOLEANS[raw], "env")
