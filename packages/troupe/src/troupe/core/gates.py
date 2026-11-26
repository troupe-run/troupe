"""Gates: who may let a worktree run's work through (spec: gates; manual-gates design D5).

The role names an approvers list may hold, the built-in default list, and the rules for a list
are here and nowhere else. Roles config (#148, #61) widens the names: until it exists, a list holds
only ``troupe``, troupe's automatic approver, and ``director``, held by whoever runs troupe.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from troupe.core.errors import TroupeError
from troupe.core.events.lineage import System
from troupe.platform.processes import host_name

TROUPE = "troupe"
"""troupe's own approver: it approves a run whose diff applies cleanly, and passes otherwise."""
DIRECTOR = "director"
"""The role whoever runs troupe holds until roles config says who holds it (decision 1)."""
ROLES = (TROUPE, DIRECTOR)
PERSON_ROLES = (DIRECTOR,)
"""The roles a person can hold: a list must end in one, so work never waits with nobody cued."""
DEFAULT_APPROVERS: tuple[str, ...] = (TROUPE, DIRECTOR)
"""An actor that sets no approvers gets these (decision 6)."""

ApproversSource = Literal["actor", "default"]


@dataclass(frozen=True)
class Approvers:
    """A run's approvers, in order, and where they came from."""

    value: tuple[str, ...]
    source: ApproversSource

    def to_data(self) -> dict[str, object]:
        return {"value": list(self.value), "source": self.source}


def resolve(configured: Sequence[str] | None) -> Approvers:
    """The approvers a run of an actor uses: its own list, or the default."""
    if configured is None:
        return Approvers(DEFAULT_APPROVERS, "default")
    return Approvers(tuple(configured), "actor")


@dataclass(frozen=True)
class Rule:
    """A rule an approvers list breaks, and how to fix it."""

    rule: str
    fix: str


def approvers_problems(approvers: Sequence[str], *, workspace: str | None) -> list[Rule]:
    """Every rule ``approvers`` breaks on an actor whose workspace is ``workspace`` (None: the
    default, a worktree). The schema has already checked that it's a list of role names."""
    if workspace == "theatre":
        return [
            Rule(
                "an actor that works in the theatre has no gate: its work lands as it's made",
                "Unset approvers, or set workspace to worktree.",
            )
        ]
    found: list[Rule] = []
    unknown = [name for name in approvers if name not in ROLES]
    if unknown:
        found.append(
            Rule(
                f"{', '.join(unknown)} isn't a role an approver can hold: until roles config, the "
                f"roles are {TROUPE} and {DIRECTOR}",
                f"Name only {TROUPE} and {DIRECTOR}.",
            )
        )
    repeated = sorted({name for name in approvers if list(approvers).count(name) > 1})
    if repeated:
        found.append(Rule(f"{', '.join(repeated)} is named more than once", "Name each role once."))
    if TROUPE in approvers[1:]:
        found.append(
            Rule(
                f"{TROUPE} can come only first: after a person, it could never be reached",
                f"Move {TROUPE} to the front, or remove it.",
            )
        )
    if not approvers or approvers[-1] not in PERSON_ROLES:
        found.append(
            Rule(
                "the last approver must be a role a person can hold, such as "
                f"{DIRECTOR}, so work never waits with nobody asked",
                f"End the list with {DIRECTOR}, or unset approvers to get the default, "
                f"{', '.join(DEFAULT_APPROVERS)}.",
            )
        )
    return found


def troupe_actor() -> System:
    """troupe acting by itself: the core, on this host (#15; design D2)."""
    return System(id=f"core@{host_name()}")


def waiting_at_gate(run_id: str, role: str, *, discarding: bool) -> TroupeError:
    """accept or discard of a run whose cue is open (spec: run-workspaces, "Accept and discard
    leave an open cue to its answer")."""
    answer = "reject" if discarding else "approve"
    command = f"troupe {answer} {run_id[:8]}"
    return TroupeError(
        "run.waiting-at-gate",
        problem=f"Run {run_id} waits at its gate for {role}, so its changes are settled by "
        f"{role}'s answer, not by {'discard' if discarding else 'accept'}.",
        fix=f"Answer the gate: {command}",
        details={"run": run_id, "role": role, "command": command},
    )


def no_cue(run_id: str, state: str) -> TroupeError:
    """approve or reject of a run with no open cue (spec: gates, "A cue is answered once")."""
    fix = (
        f"Its changes are pending, with no gate: keep them with troupe accept {run_id[:8]}, or "
        f"throw them away with troupe discard {run_id[:8]}."
        if state == "pending"
        else f"See what its changes are with troupe status {run_id[:8]}."
    )
    return TroupeError(
        "gate.no-cue",
        problem=f"Run {run_id} has no open cue to answer: its changes are {state}.",
        fix=fix,
        details={"run": run_id, "state": state},
    )


def not_a_holder(role: str, kind: str) -> TroupeError:
    """An answer from an identity that doesn't hold ``role`` (spec: gates, "Whoever runs troupe
    holds director")."""
    return TroupeError(
        "gate.not-a-holder",
        problem=f"An {kind} can't answer for {role}: until roles config, only a person holds "
        f"{role}.",
        fix="Answer as a person: unset TROUPE_ACTOR, or set it to human:<id>.",
        details={"role": role, "kind": kind},
    )
