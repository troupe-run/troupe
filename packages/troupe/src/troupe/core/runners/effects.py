"""Effect checks: did the run do what it was for? (spec: actor-runners; design D10).

A run succeeds only when its result is ok, its effect check passes and the runner exits cleanly.
EffectCheck is the port: ``before()`` runs before the runner starts, ``after()`` once it has
finished. There is no default check; a caller with no effect to check says so with
NoEffectExpected. Stages bring the real post-run audit later, through the same port.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from troupe.core.errors import TroupeError


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
