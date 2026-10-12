"""Stages: where an actor runs, and whether its effects are enforced (spec: stages;
perform-status-logs design D5).

A stage is a port. Each implementation is its own package, registered in the ``troupe.stages``
entry point group and found by name; troupe never imports one. Before a runner starts, the stage
admits the actor, saying whether its effects are enforced and, when they aren't, which policy
setting allowed that, or refuses it with stage.effects-unenforced. The admission is exactly what
lineage records about the stage (design D7). The port gains the actor's declared effects when
config defines them.
"""

import importlib.metadata
from pathlib import Path
from typing import Protocol

from troupe.core.errors import TroupeError
from troupe.core.events.lineage import StageLineage
from troupe.core.policy import Policy

ENTRY_POINT_GROUP = "troupe.stages"

Admission = StageLineage
"""A stage's admission of an actor: its name, whether effects are enforced, and what allowed an
unenforced run. Recorded in the lineage of every event the run records."""


class Stage(Protocol):
    @property
    def name(self) -> str: ...

    def workspace(self, theatre: Path) -> Path:
        """The directory the actor runs in."""
        ...

    def admit(self, policy: Policy) -> Admission:
        """Admit the actor, or refuse it with stage.effects-unenforced. Nothing may run or be
        recorded before this."""
        ...


def installed_stages() -> dict[str, importlib.metadata.EntryPoint]:
    """The stages installed, by name."""
    return {entry.name: entry for entry in importlib.metadata.entry_points(group=ENTRY_POINT_GROUP)}


def load_stage(name: str) -> Stage:
    """The stage registered as ``name``."""
    stages = installed_stages()
    if name not in stages:
        installed = ", ".join(sorted(stages)) or "none"
        raise TroupeError(
            "stage.unknown",
            problem=f"No stage named {name!r} is installed (installed: {installed}).",
            fix="Use one of the installed stages, or install the package that provides this one.",
            details={"stage": name, "installed": sorted(stages)},
        )
    factory = stages[name].load()
    stage: Stage = factory()
    return stage
