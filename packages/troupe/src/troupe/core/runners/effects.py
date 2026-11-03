"""Effect checks: did the run do what it was for? (spec: actor-runners; design D10).

A run succeeds only when its result is ok, its effect check passes and the runner exits cleanly.
EffectCheck is the port: ``before()`` runs before the runner starts, ``after()`` once it has
finished. There is no default check; a caller with no effect to check says so with
NoEffectExpected. Stages bring the real post-run audit later, through the same port.
"""

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from troupe.core.errors import TroupeError
from troupe_plugin_sdk.effects import Effect, Effects


@dataclass(frozen=True)
class EffectVerdict:
    passed: bool
    error: TroupeError | None = None

    def __post_init__(self) -> None:
        if self.passed == (self.error is not None):
            raise ValueError("a failed effect verdict carries an error, and a passed one doesn't")


class EffectCheck(Protocol):
    def before(self) -> None: ...

    def after(self) -> EffectVerdict: ...


class NoEffectExpected:
    """For a run with nothing to check: always passes, and must be chosen explicitly."""

    def before(self) -> None:
        return None

    def after(self) -> EffectVerdict:
        return EffectVerdict(passed=True)


def _hash(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return None


class ExpectedFiles:
    """Each path must exist after the run with contents that differ from before it (or be new)."""

    def __init__(self, paths: Sequence[Path]) -> None:
        if not paths:
            raise ValueError("ExpectedFiles needs at least one path; use NoEffectExpected instead")
        self.paths = [Path(path).absolute() for path in paths]
        self._before: dict[Path, str | None] = {}

    def before(self) -> None:
        self._before = {path: _hash(path) for path in self.paths}

    def after(self) -> EffectVerdict:
        for path in self.paths:
            now = _hash(path)
            if now is None:
                return EffectVerdict(
                    passed=False,
                    error=TroupeError(
                        "run.effect-missing",
                        problem="The runner reported success, but a file the run was expected to "
                        "produce doesn't exist.",
                        fix="Check the run's transcript for what the actor did instead.",
                        path=str(path),
                    ),
                )
            if now == self._before.get(path):
                return EffectVerdict(
                    passed=False,
                    error=TroupeError(
                        "run.effect-missing",
                        problem="The runner reported success, but a file the run was expected to "
                        "change is unchanged.",
                        fix="Check the run's transcript for what the actor did instead.",
                        path=str(path),
                    ),
                )
        return EffectVerdict(passed=True)


# The audit of a run's changes against its declared effects (spec: effects; declared-effects
# design D3, D4).

States = Callable[[], Mapping[str, str]]
"""Reads the workspace's files as the VCS would record them: path to content id
(Vcs.file_states)."""


@dataclass(frozen=True)
class Change:
    """One change outside the declaration: what happened to which path, and the effect it needed."""

    path: str
    change: Literal["added", "modified", "removed", "moved"]
    needs: Effect
    to: str | None = None
    """For a move, where the file went."""

    def to_data(self) -> dict[str, str]:
        data = {"path": self.path, "change": self.change, "needs": self.needs}
        if self.to is not None:
            data["to"] = self.to
        return data

    def shown(self) -> str:
        if self.change == "moved":
            return f"{self.path} moved to {self.to} (needs {self.needs})"
        return f"{self.path} {self.change} (needs {self.needs})"


def outside(effects: Effects, before: Mapping[str, str], after: Mapping[str, str]) -> list[Change]:
    """Each change from ``before`` to ``after`` that ``effects`` doesn't allow, in path order. A
    file removed and a file added with the same content id are one move, paired in path order."""
    removed = sorted(path for path in before if path not in after)
    added = sorted(path for path in after if path not in before)
    modified = sorted(path for path in before if path in after and before[path] != after[path])
    found: list[Change] = []
    unpaired = list(added)
    for path in removed:
        to = next((a for a in unpaired if after[a] == before[path]), None)
        if to is None:
            if not effects.allows("delete", path):
                found.append(Change(path, "removed", "delete"))
            continue
        unpaired.remove(to)
        as_move = effects.allows("move", path) and effects.allows("move", to)
        apart = effects.allows("delete", path) and effects.allows("write", to)
        if not (as_move or apart):
            found.append(Change(path, "moved", "move", to=to))
    for path in unpaired:
        if not effects.allows("write", path):
            found.append(Change(path, "added", "write"))
    for path in modified:
        if not effects.allows("write", path):
            found.append(Change(path, "modified", "write"))
    return sorted(found, key=lambda change: change.path)


def _fix(actor: str, effects: Effects, changes: Sequence[Change]) -> str:
    """The one troupe config set that would declare every change."""
    wanted: dict[Effect, list[str]] = {}
    for change in changes:
        paths = [change.path] if change.change != "moved" else [change.path, str(change.to)]
        listed = wanted.setdefault(change.needs, list(effects.declared(change.needs)))
        listed.extend(path for path in paths if path not in listed)
    assignments = " ".join(
        f"actors.{actor}.effects.{effect}='{json.dumps(paths)}'"
        for effect, paths in sorted(wanted.items())
    )
    return (
        "Check the run's changes with troupe diff. If they're what the actor is for, declare them "
        f"and run it again: troupe config set {assignments}"
    )


class DeclaredEffects:
    """The audit: every change in the workspace must be allowed by the actor's declared effects.
    ``before`` reads the workspace as it was when the run started (for a worktree, its baseline),
    ``after`` as it is now."""

    def __init__(
        self,
        actor: str,
        effects: Effects,
        before: States,
        after: States,
        *,
        in_theatre: bool = False,
    ) -> None:
        self.actor = actor
        self.effects = effects
        self.in_theatre = in_theatre
        self._read_before = before
        self._read_after = after
        self._before: Mapping[str, str] = {}

    def before(self) -> None:
        self._before = dict(self._read_before())

    def after(self) -> EffectVerdict:
        changes = outside(self.effects, self._before, self._read_after())
        if not changes:
            return EffectVerdict(passed=True)
        listed = "; ".join(change.shown() for change in changes)
        whose = (
            " A run in the theatre counts every change made there while it ran, by anyone."
            if self.in_theatre
            else ""
        )
        return EffectVerdict(
            passed=False,
            error=TroupeError(
                "effects.outside-declared",
                problem=f"The run changed {len(changes)} "
                f"{'file' if len(changes) == 1 else 'files'} its actor doesn't declare: "
                f"{listed}.{whose}",
                fix=_fix(self.actor, self.effects, changes),
                details={"actor": self.actor, "changes": [c.to_data() for c in changes]},
            ),
        )


class Combined:
    """Several effect checks as one: it passes when each passes. One failure is that check's
    error; more than one is effects.check-failed, holding each."""

    def __init__(self, *checks: EffectCheck) -> None:
        self.checks = checks

    def before(self) -> None:
        for check in self.checks:
            check.before()

    def after(self) -> EffectVerdict:
        errors = [
            verdict.error
            for verdict in (check.after() for check in self.checks)
            if verdict.error is not None
        ]
        if not errors:
            return EffectVerdict(passed=True)
        if len(errors) == 1:
            return EffectVerdict(passed=False, error=errors[0])
        return EffectVerdict(
            passed=False,
            error=TroupeError(
                "effects.check-failed",
                problem="The run's effect check failed more than one way: "
                + " ".join(error.problem for error in errors),
                fix=" ".join(dict.fromkeys(error.fix for error in errors)),
                details={"errors": [error.to_data() for error in errors]},
            ),
        )
