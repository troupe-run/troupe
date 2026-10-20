"""The version-control port (spec: vcs; event-store design D1, D4, D7).

troupe reads the working tree's state only through a VCS adapter: the branch, HEAD, which files are
committed, and the identity the VCS is configured with. Adapters are separately packaged and found
by name through the ``troupe.vcs`` entry point group (load_vcs); troupe never imports one.

Paths given to and returned by an adapter are relative to the theatre, with ``/`` separators.
"""

import importlib.metadata
import os
from collections.abc import Hashable
from pathlib import Path
from typing import Protocol

from troupe.core.errors import TroupeError

ENTRY_POINT_GROUP = "troupe.vcs"


class Vcs(Protocol):
    """What troupe needs to know about version control. Callers depend only on this."""

    @property
    def name(self) -> str:
        """The adapter's name, as lineage records it: ``git`` or ``files``."""
        ...

    def branch(self) -> str | None:
        """The checked-out branch; None when HEAD is detached or there are no branches.

        It is the branch at the time of the call. An adapter may answer from a cache only while
        its branch token is unchanged (cache-vcs-state design D5).
        """
        ...

    def head(self) -> str | None:
        """The HEAD commit; None before the first commit or without version control.

        It is HEAD at the time of the call, cached only as ``branch`` may be.
        """
        ...

    def branch_token(self) -> Hashable:
        """A cheap value that changes whenever the branch, HEAD or what is committed changes.

        It changes whichever process made the change. Reading it runs no command while nothing has
        moved, so a caller asks for the branch again only when the token changes (event-store
        design D4). An adapter that can't promise this returns a value that never compares equal,
        such as a fresh ``object()``, which turns its callers' caching off (cache-vcs-state D5).
        """
        ...

    def committed_under(self, directory: str) -> frozenset[str]:
        """Every committed file under ``directory``: in HEAD or the index (staged counts).

        A committed file no longer travels with a branch switch; an uncommitted one does.
        """
        ...

    def configured_identities(self) -> tuple[str, ...]:
        """The identity the VCS is configured with, from its most specific setting.

        Empty when none is set (or it is set empty). More than one value means the setting is
        ambiguous, and the caller must refuse rather than pick one.
        """
        ...


def is_committed(vcs: Vcs, path: str) -> bool:
    """Whether the theatre-relative ``path`` is committed."""
    parent = path.rpartition("/")[0] or "."
    return path in vcs.committed_under(parent)


def installed_adapters() -> dict[str, importlib.metadata.EntryPoint]:
    return {ep.name: ep for ep in importlib.metadata.entry_points(group=ENTRY_POINT_GROUP)}


def load_vcs(name: str, theatre: str | os.PathLike[str]) -> Vcs:
    """The VCS adapter registered as ``name``, for the theatre at ``theatre``."""
    adapters = installed_adapters()
    if name not in adapters:
        installed = ", ".join(sorted(adapters)) or "none"
        raise TroupeError(
            "vcs.unknown-adapter",
            problem=f"No version-control adapter named {name!r} is installed "
            f"(installed: {installed}).",
            fix="Use one of the installed adapters, or install the package that provides this one.",
            details={"adapter": name, "installed": sorted(adapters)},
        )
    factory = adapters[name].load()
    vcs: Vcs = factory(Path(theatre))
    return vcs
