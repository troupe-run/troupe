"""What a performance runs: its steps, each an actor as config defines it, with the approvers its
gate tries and what it's told (spec: performances, flows; actor-sequences design D2).

A perform resolves its name to a plan before anything is recorded: an actor is a plan of one step,
and a flow a plan of its steps. Every check that can refuse runs over every step, so one refusal
refuses the whole performance. The driver in troupe.core.runs.perform then runs the steps from a
given index, which is how approve carries a waiting flow on.
"""

from dataclasses import dataclass, field
from typing import Any, Literal

from troupe.core import defaults, gates
from troupe.core.client import messages as m
from troupe.core.config.merge import Merged
from troupe.core.config_paths import shown
from troupe.core.errors import TroupeError
from troupe.core.policy import PolicyCompaction, env_name
from troupe.core.runs.backends import Backends as Backends
from troupe.core.runs.backends import lease_dir as lease_dir
from troupe.core.workspaces import (
    Kind,
)
from troupe_plugin_sdk import runner as p

ApproversSource = Literal["step", "actor", "default"]


@dataclass(frozen=True)
class StepApprovers:
    """A step's approvers, in order, and where they came from: the step in its flow, its actor,
    or troupe's default (spec: flows, "A step's approvers come from the step, its actor, or the
    default")."""

    value: tuple[str, ...]
    source: ApproversSource

    def to_data(self) -> dict[str, object]:
        return {"value": list(self.value), "source": self.source}


def step_approvers(step: tuple[str, ...] | None, actor: tuple[str, ...] | None) -> StepApprovers:
    """The approvers a step's gate tries: the step's own, else its actor's, else the default."""
    if step is not None:
        return StepApprovers(step, "step")
    resolved = gates.resolve(actor)
    return StepApprovers(resolved.value, resolved.source)


@dataclass(frozen=True)
class Performed:
    """What a performance performs: an actor or a flow, by its name then."""

    kind: Literal["actor", "flow"]
    name: str

    def to_data(self) -> dict[str, str]:
        return {"kind": self.kind, "name": self.name}


@dataclass(frozen=True)
class StepPosition:
    """Where a run is in its performance: its step, counting from 1, of how many."""

    index: int
    total: int

    @property
    def first(self) -> bool:
        return self.index == 1

    @property
    def last(self) -> bool:
        return self.index == self.total


@dataclass
class PerformanceStart:
    """What the first step's run records with its start, in the same batch: the performance's
    own start (performances design D2)."""

    performance_id: str
    performed: Performed
    steps: list[dict[str, Any]] = field(default_factory=list)
    """Each step as Performance.Started records it: its actor, and its approvers with their
    source when it works in a worktree."""


@dataclass(frozen=True)
class _What:
    """What a perform runs, as config defines the actor (config-model design D14)."""

    actor: str
    runner: str
    options: dict[str, object]
    effect_check: m.EffectCheck
    character: str | None
    config: tuple[str, ...]
    workspace: Kind
    effects: p.EffectsDeclaration = p.READ_ONLY_DECLARATION
    runtime: str | None = None
    model: str | None = None
    on_context_full: str | None = None
    """The actor's own onContextFull; None when it doesn't set one."""
    approvers: tuple[str, ...] | None = None
    """The actor's own approvers; None when it doesn't set any."""

    def resolved_approvers(self) -> gates.Approvers | None:
        """The approvers its runs' gate tries: None for a run in the theatre, which has none."""
        if self.workspace != "worktree":
            return None
        return gates.resolve(self.approvers)


@dataclass(frozen=True)
class ContextFull:
    """A run's onContextFull as perform resolved it, and where it came from (compaction-opt-in
    design D2, D3)."""

    value: p.OnContextFull
    source: Literal["default", "actor", "policy"]

    def to_data(self) -> dict[str, str]:
        return {"value": self.value, "source": self.source}


def resolve_context_full(actor: str, own: str | None, policy: PolicyCompaction) -> ContextFull:
    """The run's onContextFull from the actor's own value and the compaction policy: under actors,
    the actor's value, fail when it has none; under all, compact unless the actor says fail; under
    none, fail, and an actor that asks for compact is refused with policy.compaction-forbidden."""
    if own == "compact" and policy.value == "none":
        variable = env_name(policy.setting)
        raise TroupeError(
            "policy.compaction-forbidden",
            problem=f"The actor {actor} asks to compact when its context fills "
            f"(onContextFull: compact), and policy forbids compaction ({variable}=none).",
            fix=f"Set the actor's onContextFull to fail (troupe config set "
            f"{shown(('actors', actor, 'onContextFull'))}=fail), or change {variable}.",
            details={"actor": actor, "variable": variable},
        )
    if own == "compact":
        return ContextFull("compact", "actor")
    if own == "fail":
        return ContextFull("fail", "actor")
    if policy.value == "all":
        return ContextFull("compact", "policy")
    if policy.value == "none":
        return ContextFull("fail", "policy")
    return ContextFull("fail", "default")


def _from_config(merged: Merged, name: str) -> _What:
    """The actor ``name`` as config defines it. Refused when config has no such actor."""
    actors = merged.config.get("actors", {})
    actor = actors.get(name) if isinstance(actors, dict) else None
    if not isinstance(actor, dict):
        known = sorted(actors) if isinstance(actors, dict) else []
        listed = ", ".join(known) or "none yet"
        renamed = merged.names.renamed_to("actors", name) if merged.names is not None else None
        details: dict[str, object] = {"actor": name, "known": known}
        if renamed is not None:
            details["renamedTo"] = renamed
            fix = f"{name} was renamed {renamed}: troupe perform {renamed}."
        else:
            fix = (
                f"Perform one of the actors config has, or define {name} with troupe config "
                f"set {shown(('actors', name, 'runner'))}=... "
                f"{shown(('actors', name, 'expect'))}=..."
            )
        raise TroupeError(
            "config.unknown-actor",
            problem=f"Config has no actor named {name!r} (it has: {listed}).",
            fix=fix,
            details=details,
        )
    paths = list(dict.fromkeys(actor["expect"]))
    check: m.EffectCheck = m.FilesEffectCheck(paths=paths) if paths else m.NoEffectCheck()
    character = actor.get("character")
    workspace = actor.get("workspace", defaults.WORKSPACE)
    declared = actor.get("effects") or {}
    effects = p.EffectsDeclaration(
        write=list(declared.get("write") or []),
        delete=list(declared.get("delete") or []),
        move=list(declared.get("move") or []),
    )
    return _What(
        actor=name,
        runner=str(actor["runner"]),
        options=dict(actor.get("options", {})),
        effect_check=check,
        character=character if isinstance(character, str) else None,
        config=merged.heads,
        workspace="theatre" if workspace == "theatre" else "worktree",
        effects=effects,
        runtime=actor.get("runtime"),
        model=actor.get("model"),
        on_context_full=actor.get("onContextFull"),
        approvers=tuple(actor["approvers"]) if "approvers" in actor else None,
    )


@dataclass(frozen=True)
class _StepPlan:
    """One step of a performance: its actor as config defines it, where it is in the
    performance, the approvers its gate tries, and what it's told (actor-sequences design D2)."""

    what: _What
    position: StepPosition = field(default_factory=lambda: StepPosition(1, 1))
    own_approvers: tuple[str, ...] | None = None
    """The step's own approvers in its flow; None when it sets none."""

    @property
    def approvers(self) -> StepApprovers | None:
        """The approvers its gate tries: None for a run in the theatre, which has none."""
        if self.what.workspace != "worktree":
            return None
        return step_approvers(self.own_approvers, self.what.approvers)

    def recorded(self) -> dict[str, Any]:
        """The step as Performance.Started records it."""
        data: dict[str, Any] = {"actor": self.what.actor}
        if self.approvers is not None:
            data["approvers"] = self.approvers.to_data()
        return data


def _approvers_data(step: _StepPlan) -> dict[str, object] | None:
    resolved = step.approvers
    return resolved.to_data() if resolved is not None else None


def _rehearsed_approvers(step: _StepPlan) -> m.ApproversData | None:
    data = _approvers_data(step)
    return m.ApproversData.from_data(data) if data is not None else None
