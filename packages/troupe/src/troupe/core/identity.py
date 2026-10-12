"""Who is acting: an ordered chain of identity sources (spec: identity; event-store design D9).

Each source is asked in turn. A source that finds nothing passes to the next; a source that finds
something it can't use cleanly (malformed, or more than one candidate) fails the command, because a
quiet fall-through would record the wrong person and nothing would show it (owner, 2026-10-12). If
no source answers, the command fails before anything is written: there is never an ``unknown``
actor, an empty id or a guess.

Sources are separately packaged and found by name through the ``troupe.identity`` entry point
group; the chain is the named setting IDENTITY_CHAIN.
"""

import importlib.metadata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from troupe.core import defaults
from troupe.core.errors import TroupeError
from troupe.core.vcs import Vcs

ENTRY_POINT_GROUP = "troupe.identity"

Kind = Literal["human", "agent"]


@dataclass(frozen=True)
class Identity:
    """Who is acting, and which source said so."""

    kind: Kind
    id: str
    source: str

    def __post_init__(self) -> None:
        if not self.id or self.id != self.id.strip():
            msg = f"an identity's id must be non-empty with no surrounding space: {self.id!r}"
            raise ValueError(msg)


@dataclass(frozen=True)
class IdentityContext:
    """What a source may look at: the environment troupe runs in, and the theatre's VCS."""

    env: Mapping[str, str]
    vcs: Vcs


class IdentitySource(Protocol):
    """One place an identity can come from."""

    @property
    def hint(self) -> str:
        """How a person provides an identity through this source, for the unresolved error."""
        ...

    def resolve(self, context: IdentityContext) -> Identity | None:
        """The identity, or None when this source has nothing. Raise a TroupeError when what it
        finds is malformed or ambiguous: never return None for that."""
        ...


def installed_sources() -> dict[str, importlib.metadata.EntryPoint]:
    return {ep.name: ep for ep in importlib.metadata.entry_points(group=ENTRY_POINT_GROUP)}


def load_sources(chain: Sequence[str]) -> list[tuple[str, IdentitySource]]:
    """The sources named in ``chain``, in order. Every name is checked before any is asked."""
    installed = installed_sources()
    unknown = [name for name in chain if name not in installed]
    if unknown:
        raise TroupeError(
            "identity.unknown-source",
            problem=f"The identity chain names {_names(unknown)}, which isn't installed "
            f"(installed: {_names(sorted(installed)) or 'none'}).",
            fix="Use only installed identity sources in the chain, or install the package that "
            "provides the missing one.",
            details={"unknown": unknown, "installed": sorted(installed), "chain": list(chain)},
        )
    return [(name, installed[name].load()()) for name in chain]


def resolve_identity(
    context: IdentityContext,
    *,
    chain: Sequence[str] = defaults.IDENTITY_CHAIN,
    sources: Sequence[tuple[str, IdentitySource]] | None = None,
) -> Identity:
    """Ask each source in ``chain`` in turn and return the first answer."""
    named = load_sources(chain) if sources is None else list(sources)
    for _name, source in named:
        identity = source.resolve(context)
        if identity is not None:
            return identity
    raise TroupeError(
        "identity.unresolved",
        problem=f"troupe couldn't work out who is acting: none of the identity sources "
        f"({_names([name for name, _ in named])}) had an answer.",
        fix="Provide an identity through one of them: "
        + "; ".join(f"{name}: {source.hint}" for name, source in named)
        + ".",
        details={"tried": [name for name, _ in named]},
    )


def _names(names: Sequence[str]) -> str:
    return ", ".join(repr(name) for name in names)
