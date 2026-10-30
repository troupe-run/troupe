"""Settings: the one seam through which every setting that isn't policy is read (spec: settings;
mark-config-resolved design D1).

A setting is a person's preference, which policy bounds; policy is authoritative and only tightens
(troupe.core.policy). Each setting has its default in troupe.core.defaults, and each value read
carries the source it came from. Until policy files and house config bring levels (#71, #2), the
only source above the default is the environment: ``TROUPE_SETTING_`` and the setting's name in
capitals. An unset or empty variable is absent and falls through to the default; anything else that
isn't an accepted value is an error, never a quiet default. Settings never come from a request:
they are read from the session's environment.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from troupe.core import defaults
from troupe.core.errors import TroupeError
from troupe.core.policy import read_mark_merges_resolved

ENV_PREFIX = "TROUPE_SETTING_"
MARK_MERGES_RESOLVED = "mark_merges_resolved"

SettingSource = Literal["default", "env"]
BOOLEANS = {"true": True, "false": False}


@dataclass(frozen=True)
class SettingFlag:
    """A boolean setting's value, and where it came from."""

    setting: str
    value: bool
    source: SettingSource


@dataclass(frozen=True)
class Settings:
    """Every setting troupe has, read once for a command."""

    mark_merges_resolved: SettingFlag


def env_name(setting: str) -> str:
    """The environment variable that sets ``setting``."""
    return ENV_PREFIX + setting.upper()


def read_settings(env: Mapping[str, str]) -> Settings:
    """The settings in effect for a command run with ``env``. Raises settings.invalid-value for a
    malformed value."""
    return Settings(
        mark_merges_resolved=_flag(MARK_MERGES_RESOLVED, defaults.MARK_MERGES_RESOLVED, env)
    )


def _flag(setting: str, default: bool, env: Mapping[str, str]) -> SettingFlag:
    name = env_name(setting)
    raw = env.get(name, "")
    if raw == "":
        return SettingFlag(setting, default, "default")
    if raw not in BOOLEANS:
        raise TroupeError(
            "settings.invalid-value",
            problem=f"The setting variable {name} is set to {raw!r}, which isn't true or false.",
            fix=f"Set {name} to exactly true or false, or unset it to use the default "
            f"({str(default).lower()}).",
            details={"variable": name, "value": raw, "accepted": sorted(BOOLEANS)},
        )
    return SettingFlag(setting, BOOLEANS[raw], "env")


@dataclass(frozen=True)
class Marking:
    """Whether a command marks the config files it rewrote from a conflicted merge resolved in
    git's index, and if not, why not (design D2)."""

    on: bool
    off_because: Literal["setting", "policy"] | None = None


def marking(env: Mapping[str, str]) -> Marking:
    """The marking in effect for a command run with ``env``. The setting is always read, so a
    malformed one fails any command that uses config (design D7); policy is read only when the
    setting is on, since nothing else needs it."""
    if not read_settings(env).mark_merges_resolved.value:
        return Marking(False, "setting")
    if not read_mark_merges_resolved(env).value:
        return Marking(False, "policy")
    return Marking(True)
