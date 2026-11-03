"""An actor's declaration as one run has it, and the seam runners apply it through (spec:
plugin-sdk, "The SDK reads the declaration from run start" and "Runners plug in their own way of
applying the declaration"; declared-effects design D7).

A runner reads its ``run/start`` into a ``Declaration``: the effects, the workspace and the run's
scratch directory. It then applies the declaration its own way, through an ``EffectsTranslation``:
the SDK's own tools check each call (``checked``); a runner driving an engine with rules of its own
translates the declaration into them (``translated``). Every translation sees the same normalised
view, so two runners can't disagree about what a pattern means on a platform.

    declaration = Declaration.from_run_start(params)
    rules = MyEngineRules().translate(declaration)
"""

from dataclasses import dataclass
from pathlib import Path, PurePath, PureWindowsPath
from typing import Literal, Protocol, TypeVar

from troupe_plugin_sdk.effects import EFFECTS, Effect, Effects, PatternError
from troupe_plugin_sdk.messages import ProtocolError
from troupe_plugin_sdk.runner import RunStartParams

Mode = Literal["checked", "translated"]
"""How a runner applies the declaration, as its ``init`` event reports it."""

T_co = TypeVar("T_co", covariant=True)


def posix_absolute(path: PurePath) -> str:
    """An absolute path in one form on every platform: ``/`` between parts, and a Windows drive
    as a lowercase first part (``C:\\work`` is ``/c/work``). Raises ValueError for a path that
    isn't absolute, or a Windows path with no drive letter (a UNC share)."""
    if not path.is_absolute():
        raise ValueError(f"{str(path)!r} isn't an absolute path")
    if isinstance(path, PureWindowsPath):
        drive = path.drive
        if len(drive) != 2 or drive[1] != ":" or not drive[0].isalpha():
            raise ValueError(f"{str(path)!r} has no drive letter; a share isn't supported")
        parts = [drive[0].lower(), *path.parts[1:]]
        return "/" + "/".join(parts)
    return path.as_posix()


@dataclass(frozen=True)
class Declaration:
    """What one run may change: its effects, the workspace they're relative to, and its scratch
    directory, which needs no effect."""

    effects: Effects
    workspace: PurePath
    scratch: PurePath | None = None

    @classmethod
    def from_run_start(cls, params: RunStartParams) -> "Declaration":
        """The declaration a ``run/start`` carries. Raises ProtocolError naming the effect and the
        pattern when one is malformed."""
        declared = params.effects
        try:
            effects = Effects(
                write=tuple(declared.write),
                delete=tuple(declared.delete),
                move=tuple(declared.move),
            )
        except PatternError as error:
            raise ProtocolError(f"run/start effects: {error}") from error
        return cls(effects, Path(params.workspace), Path(params.scratch))

    def absolute(self, effect: Effect) -> tuple[str, ...]:
        """Each ``effect`` pattern rooted at the workspace, in ``posix_absolute`` form."""
        if effect not in EFFECTS:
            raise ValueError(f"{effect!r} isn't an effect (the effects are: {', '.join(EFFECTS)})")
        root = posix_absolute(self.workspace).rstrip("/")
        return tuple(f"{root}/{pattern}" for pattern in self.effects.declared(effect))

    def workspace_absolute(self) -> str:
        """The workspace in ``posix_absolute`` form."""
        return posix_absolute(self.workspace)

    def scratch_absolute(self) -> str | None:
        """The scratch directory in ``posix_absolute`` form, or None when the run has none."""
        return None if self.scratch is None else posix_absolute(self.scratch)


class EffectsTranslation(Protocol[T_co]):
    """A runner's way of applying a declaration: its ``mode``, reported as ``init``'s
    ``effects``, and what it makes of a declaration (rules, a settings file, a checker)."""

    @property
    def mode(self) -> Mode: ...

    def translate(self, declaration: Declaration) -> T_co: ...
