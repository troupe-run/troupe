"""Turning a model's path into a checked path in the workspace (spec: runner-tools; runner-sdk
design D6).

This is the one place the path rules live. They're the same on every platform, so a model gets the
same answer wherever its runner runs:

1. **Syntax.** A path is relative to the workspace, with ``/`` between its parts. Refused: an empty
   path, an absolute one, ``..``, ``\\``, ``:`` (drive letters and Windows' alternate streams),
   control characters, Windows' reserved device names (``CON``, ``NUL``, ``COM1`` and the rest,
   with any extension), and parts that end in a dot or a space. ``.`` parts and repeated ``/`` are
   dropped.
2. **``.git``.** A path whose first part is ``.git``, in any case, is refused.
3. **Resolve.** The path is joined to the workspace and resolved, which follows symbolic links and
   Windows junctions. The result must be inside the workspace.
4. **The changed path.** The resolved path, made workspace-relative again, is what the effects and
   the ``.git`` rule are checked against, so a link can't carry a call somewhere it isn't allowed.

Standard library only: ``pathlib`` and ``os``.
"""

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

GIT = ".git"

_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{n}" for n in "123456789¹²³"}
    | {f"LPT{n}" for n in "123456789¹²³"}
)
"""Windows' reserved device names. A file named one of them, with any extension, can't be made on
Windows, so they're refused everywhere."""

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class PathRefusedError(ValueError):
    """A path a tool won't use, with what's wrong, phrased for the model."""

    def __init__(self, path: str, problem: str) -> None:
        super().__init__(problem)
        self.path = path
        self.problem = problem


def parts_of(text: str) -> tuple[str, ...]:
    """The parts of a workspace-relative path, after the syntax rules (step 1). An empty tuple is
    the workspace itself. Raises PathRefusedError naming what's wrong."""
    shown = repr(text)
    if not text:
        raise PathRefusedError(text, "The path is empty. Give a path relative to the workspace.")
    if _CONTROL.search(text):
        raise PathRefusedError(text, f"The path {shown} has a control character in it.")
    if "\\" in text:
        raise PathRefusedError(
            text, f"The path {shown} has a backslash in it. Use / between the parts of a path."
        )
    if ":" in text:
        raise PathRefusedError(
            text,
            f"The path {shown} has a colon in it. Paths are relative to the workspace, with no "
            "drive letter.",
        )
    if text.startswith("/"):
        raise PathRefusedError(
            text,
            f"The path {shown} is absolute. Paths are relative to the workspace, such as "
            "src/main.py.",
        )
    parts = tuple(part for part in text.split("/") if part not in ("", "."))
    for part in parts:
        if part == "..":
            raise PathRefusedError(
                text, f"The path {shown} uses '..'. Paths stay inside the workspace."
            )
        if part.endswith((".", " ")):
            raise PathRefusedError(
                text, f"The path {shown} has a part ending in a dot or a space: {part!r}."
            )
        if part.split(".", 1)[0].upper() in _RESERVED:
            raise PathRefusedError(
                text, f"The path {shown} uses {part!r}, a name Windows reserves for a device."
            )
    return parts


def _is_git(parts: tuple[str, ...]) -> bool:
    return bool(parts) and parts[0].casefold() == GIT


@dataclass(frozen=True)
class WorkspacePath:
    """A checked path: where it is, and its workspace-relative form after links are followed."""

    given: str
    """What the model wrote."""
    relative: str
    """The path the call would act on, relative to the workspace with ``/``, after links. Empty for
    the workspace itself."""
    absolute: Path
    """The same path on this machine."""


class Workspace:
    """The directory a run works in. Every path a tool takes goes through ``path``."""

    def __init__(self, root: Path) -> None:
        resolved = Path(root).resolve(strict=True)
        if not resolved.is_dir():
            raise ValueError(f"the workspace {root} isn't a directory")
        self.root = resolved

    def path(self, text: str, *, directory: bool = False) -> WorkspacePath:
        """``text`` as a checked path. With ``directory``, the workspace itself (``.``) is allowed,
        for a tool that searches from it. Raises PathRefusedError naming what's wrong."""
        parts = parts_of(text)
        if not parts and not directory:
            raise PathRefusedError(
                text, f"The path {text!r} names the workspace itself, not a file."
            )
        if _is_git(parts):
            raise PathRefusedError(
                text,
                f"The path {text!r} is in .git, the repository's own data, which is off limits.",
            )
        resolved = self.root.joinpath(*parts).resolve()
        if not resolved.is_relative_to(self.root):
            raise PathRefusedError(
                text, f"The path {text!r} leads outside the workspace, through a link."
            )
        relative = PurePosixPath(*resolved.relative_to(self.root).parts)
        if _is_git(relative.parts):
            raise PathRefusedError(
                text,
                f"The path {text!r} leads into .git, the repository's own data, which is off "
                "limits.",
            )
        shown = "" if not relative.parts else relative.as_posix()
        return WorkspacePath(given=text, relative=shown, absolute=resolved)

    def contains(self, path: Path) -> bool:
        """Whether ``path``, with links followed, is inside the workspace and outside ``.git``."""
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root):
            return False
        return not _is_git(resolved.relative_to(self.root).parts)
