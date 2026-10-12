"""troupe's local identity sources: env, vcs and os-login (spec: identity; design D9).

- ``env``: the ``TROUPE_ACTOR`` override, ``human:<id>`` or ``agent:<id>``. Unset or empty is no
  answer; anything else that isn't one of those forms is an error, never a fall-through.
- ``vcs``: the identity the VCS adapter is configured with (git's ``user.email``). None configured
  is no answer; more than one in the winning setting is an error.
- ``os-login``: the login name of the account troupe runs as.

Each is registered in the ``troupe.identity`` entry point group and found by name.
"""

import getpass
import re
from collections.abc import Callable

from troupe.core.errors import TroupeError
from troupe.core.identity import Identity, IdentityContext

OVERRIDE = "TROUPE_ACTOR"
_OVERRIDE_FORM = re.compile(r"^(human|agent):(\S(?:.*\S)?)$")


class EnvSource:
    """The ``TROUPE_ACTOR`` override."""

    hint = f"set {OVERRIDE} to human:<id> or agent:<id>"

    def resolve(self, context: IdentityContext) -> Identity | None:
        value = context.env.get(OVERRIDE, "")
        if value == "":
            return None
        match = _OVERRIDE_FORM.match(value)
        if match is None:
            raise TroupeError(
                "identity.invalid-override",
                problem=f"{OVERRIDE} is {value!r}, which isn't an identity troupe can use.",
                fix=f"Set {OVERRIDE} to human:<id> or agent:<id>, such as "
                "human:ada@example.com, or unset it to use the next identity source.",
                details={"source": "env", "variable": OVERRIDE, "value": value},
            )
        if match.group(1) == "human":
            return Identity(kind="human", id=match.group(2), source="env")
        return Identity(kind="agent", id=match.group(2), source="env")


class VcsSource:
    """The identity the theatre's VCS is configured with."""

    hint = "set user.email in git (git config user.email you@example.com)"

    def resolve(self, context: IdentityContext) -> Identity | None:
        values = context.vcs.configured_identities()
        if not values:
            return None
        if len(values) > 1:
            raise TroupeError(
                "identity.ambiguous",
                problem=f"The {context.vcs.name} configuration has {len(values)} identities "
                f"({', '.join(values)}), so troupe can't tell which one is acting.",
                fix="Keep one user.email in that configuration file (git config --unset-all "
                "user.email, then set the one you want), or set TROUPE_ACTOR.",
                details={"source": "vcs", "adapter": context.vcs.name, "values": list(values)},
            )
        return Identity(kind="human", id=values[0].strip(), source="vcs")


class OsLoginSource:
    """The login name of the account troupe runs as."""

    hint = "run troupe as a named user account"

    def __init__(self, lookup: Callable[[], str] = getpass.getuser) -> None:
        self.lookup = lookup

    def resolve(self, context: IdentityContext) -> Identity | None:
        try:
            name = self.lookup().strip()
        except (OSError, KeyError):
            return None  # no login name at all: absent, not malformed
        if not name:
            return None
        return Identity(kind="human", id=name, source="os-login")
