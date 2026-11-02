"""An actor's declared effects, and the path patterns they're made of (spec: runner-tools;
runner-sdk design D7).

An actor declares three lists of workspace-relative path patterns: where it may write (``Write``
and ``Edit``), where it may delete, and where it may move files. Deleting and moving are their own
effects, declared apart from writing, because they're more destructive. With nothing declared, an
actor is read-only. #241 builds an ``Effects`` from actor config.

A pattern has one language, shared with the ``Glob`` tool: ``*`` matches any characters within one
part of a path, ``?`` matches one character, and ``**``, as a whole part, matches any number of
whole parts. Anything else matches itself. Matching is case-sensitive on every platform, so on a
case-insensitive filesystem it refuses more, never less. ``fnmatch`` lets ``*`` cross ``/``, and
``PurePath.full_match`` needs Python 3.13, so the matcher is the SDK's own.
"""

import re
from dataclasses import dataclass, field
from typing import Literal

Effect = Literal["write", "delete", "move"]
EFFECTS: tuple[Effect, ...] = ("write", "delete", "move")


class PatternError(ValueError):
    """A malformed pattern: where it is, the pattern, and what's wrong."""


def _segment(part: str) -> str:
    return "".join(
        "[^/]*" if char == "*" else "[^/]" if char == "?" else re.escape(char) for char in part
    )


def pattern_regex(pattern: str, where: str = "pattern") -> re.Pattern[str]:
    """The compiled matcher for ``pattern``. Raises PatternError naming ``where`` and the pattern
    when it's malformed: empty, absolute, with ``..``, ``\\``, ``:``, an empty part, or ``**``
    inside a part."""
    shown = f"{where}: {pattern!r}"
    if not pattern:
        raise PatternError(f"{shown} is empty")
    if pattern.startswith("/"):
        raise PatternError(f"{shown} is absolute; patterns are relative to the workspace")
    if "\\" in pattern or ":" in pattern:
        raise PatternError(f"{shown} has a '\\' or ':'; use '/' between the parts of a path")
    parts = pattern.split("/")
    for part in parts:
        if part in ("", "."):
            raise PatternError(f"{shown} has an empty part; write each part once, with one '/'")
        if part == "..":
            raise PatternError(f"{shown} uses '..'; patterns stay inside the workspace")
        if "**" in part and part != "**":
            raise PatternError(f"{shown} has '**' inside a part; '**' is a whole part of its own")
    regex = ""
    for index, part in enumerate(parts):
        last = index == len(parts) - 1
        if part == "**":
            regex += "[^/]+(?:/[^/]+)*" if last else "(?:[^/]+/)*"
        else:
            regex += _segment(part) + ("" if last else "/")
    return re.compile(rf"\A{regex}\Z")


@dataclass(frozen=True)
class PathPattern:
    """One workspace-relative path pattern, compiled once."""

    text: str
    _regex: re.Pattern[str] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_regex", pattern_regex(self.text))

    def matches(self, relative: str) -> bool:
        """Whether a workspace-relative path, with ``/`` between its parts, matches."""
        return self._regex.match(relative) is not None


def _patterns(effect: Effect, texts: tuple[str, ...]) -> tuple[PathPattern, ...]:
    if isinstance(texts, str):
        raise PatternError(f"{effect}: a list of patterns, not one string")
    for text in texts:
        pattern_regex(text, effect)  # names the effect when the pattern is malformed
    return tuple(PathPattern(text) for text in texts)


@dataclass(frozen=True)
class Effects:
    """What an actor may change, as three lists of patterns. The default is read-only."""

    write: tuple[str, ...] = ()
    delete: tuple[str, ...] = ()
    move: tuple[str, ...] = ()
    _compiled: dict[Effect, tuple[PathPattern, ...]] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        compiled = {
            "write": _patterns("write", self.write),
            "delete": _patterns("delete", self.delete),
            "move": _patterns("move", self.move),
        }
        object.__setattr__(self, "_compiled", compiled)

    def allows(self, effect: Effect, relative: str) -> bool:
        """Whether ``effect`` is declared for the workspace-relative path ``relative``."""
        return any(pattern.matches(relative) for pattern in self._compiled[effect])

    def declared(self, effect: Effect) -> tuple[str, ...]:
        """The patterns declared for ``effect``, as written."""
        return {"write": self.write, "delete": self.delete, "move": self.move}[effect]


READ_ONLY = Effects()
"""No effects declared: the actor can read and search, and change nothing."""
