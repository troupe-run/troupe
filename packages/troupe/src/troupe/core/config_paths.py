"""Config paths as people type and read them (spec: config, "A config path can put any key in
brackets", "A config path is shown in the form it is typed", "A malformed config path is refused";
config-path-dotted-keys design D1-D3).

The core's requests carry a path as an array of keys. This is the one place that turns text into
keys and keys into text, for every surface and every message: keys joined by dots, where any key
may be written in square brackets instead, with no dot before the bracket. Inside brackets only
``\\]`` and ``\\\\`` are escapes. A plain key holds none of ``. [ ] = \\``: ``=`` so that
``config set``'s ``<path>=<value>`` and the reader agree on where a path ends, and ``\\`` so that
an escape typed outside brackets (``gpt-4\\.1``) is refused instead of splitting quietly.
"""

from collections.abc import Sequence

from troupe.core.errors import TroupeError

NEEDS_BRACKETS = frozenset(".[]=\\")
"""The characters a plain key can't hold. A key holding any of them is shown in brackets."""

EMPTY = "a key can't be empty"
UNCLOSED = "the [ has no closing ]"
ESCAPES_NOTHING = "the \\ escapes nothing"
UNKNOWN_ESCAPE = "inside brackets only \\] and \\\\ are escapes"
BACKSLASH_OUTSIDE = "a backslash only escapes inside brackets"
AFTER_BRACKET = "a ] is followed by ., [ or the end"
DOT_BEFORE_BRACKET = "no dot comes before a ["
STRAY_CLOSE = "the ] closes no ["
EQUALS_OUTSIDE = "a key that holds = is written in brackets"

FIX = (
    "Write keys joined by dots, with a key that holds ., [, ], = or \\ in brackets, "
    "such as runtimes.openai.prices[gpt-4.1]."
)


def _malformed(
    text: str, offset: int, rule: str, fix: str = FIX, *, bracket: int | None = None
) -> TroupeError:
    """A refusal naming the text only up to and including the character at ``offset``: in
    ``config set``, what follows can be the value, which may hold a password (spec: config, "A
    malformed config path is refused"; config-set-json-redacts design D6). Reading never passes an
    ``=`` outside brackets. Inside a bracket it does, so a failure there (``bracket``, where the
    bracket opens) shows the text only up to that ``[``: an unclosed one can hold the value."""
    read = text[: (offset if bracket is None else bracket) + 1]
    return TroupeError(
        "config.path-malformed",
        problem=f'"{read}" isn\'t a config path: {rule} (at character {offset + 1}).',
        fix=fix,
        details={"text": read, "offset": offset, "rule": rule},
    )


def _bracket(text: str, start: int) -> tuple[str, int]:
    """The key in the brackets opening at ``start``, and where reading goes on after them."""
    at = start + 1
    key: list[str] = []
    while at < len(text):
        char = text[at]
        if char == "]":
            if not key:
                raise _malformed(text, start, EMPTY)
            return "".join(key), at + 1
        if char == "\\":
            if at + 1 == len(text):
                raise _malformed(text, at, ESCAPES_NOTHING, bracket=start)
            if text[at + 1] not in "]\\":
                raise _malformed(text, at, UNKNOWN_ESCAPE, bracket=start)
            key.append(text[at + 1])
            at += 2
            continue
        key.append(char)
        at += 1
    raise _malformed(text, start, UNCLOSED)


def _without_dot(text: str, at: int) -> str:
    """The fix for a dot before the ``[`` at ``at``: the path up to the end of that bracket with the
    dot taken out, and nothing after it, which can be the value (design D6)."""
    try:
        _, end = _bracket(text, at)
    except TroupeError:
        return "Write the key in brackets with no dot before the [, such as a[b]."
    return f"Write {text[: at - 1] + text[at:end]!r}, with no dot before the [."


def _plain(text: str, start: int) -> tuple[str, int]:
    at = start
    while at < len(text) and text[at] not in NEEDS_BRACKETS:
        at += 1
    return text[start:at], at


def _read(text: str, *, stop_at_equals: bool) -> tuple[tuple[str, ...], int]:
    keys: list[str] = []
    at = 0
    after_dot = False
    while True:
        if at < len(text) and text[at] == "[":
            if after_dot:
                raise _malformed(text, at - 1, DOT_BEFORE_BRACKET, _without_dot(text, at))
            key, at = _bracket(text, at)
        else:
            key, at = _plain(text, at)
            if not key:
                raise _key_missing(text, at, stop_at_equals=stop_at_equals)
        keys.append(key)
        after_dot = False
        if at == len(text):
            return tuple(keys), at
        char = text[at]
        if char == ".":
            at += 1
            after_dot = True
        elif char == "[":
            continue
        elif char == "=":
            if stop_at_equals:
                return tuple(keys), at
            raise _malformed(text, at, EQUALS_OUTSIDE)
        else:
            raise _misplaced(text, at)


def _key_missing(text: str, at: int, *, stop_at_equals: bool) -> TroupeError:
    """Why no key starts at ``at``: it's empty, or a character a plain key can't hold is there."""
    char = text[at] if at < len(text) else ""
    if char in ("", ".") or (char == "=" and stop_at_equals):
        return _malformed(text, at, EMPTY)
    if char == "=":
        return _malformed(text, at, EQUALS_OUTSIDE)
    return _misplaced(text, at)


def _misplaced(text: str, at: int) -> TroupeError:
    """The character at ``at`` can't come where it is: a stray ``]``, a backslash outside
    brackets, or anything but ``.``, ``[`` or the end straight after a ``]``."""
    char = text[at]
    if char == "]":
        return _malformed(text, at, STRAY_CLOSE)
    if char == "\\":
        return _malformed(
            text,
            at,
            BACKSLASH_OUTSIDE,
            "Write a key that holds a dot in brackets, such as [gpt-4.1], with no backslash.",
        )
    return _malformed(text, at, AFTER_BRACKET)


def parse(text: str) -> tuple[str, ...]:
    """The keys of the path ``text``. Refused with ``config.path-malformed`` when it can't be
    read."""
    keys, _ = _read(text, stop_at_equals=False)
    return keys


def parse_prefix(text: str) -> tuple[tuple[str, ...], int]:
    """The keys of the path at the start of ``text``, which ends at the first ``=`` outside
    brackets, and where it ended: the ``=``'s index, or ``len(text)`` when there's none."""
    return _read(text, stop_at_equals=True)


def shown(path: Sequence[str]) -> str:
    """``path`` as people read and type it: ``runtimes.openai.prices[gpt-4.1].input``."""
    parts: list[str] = []
    for key in path:
        if key and not NEEDS_BRACKETS.intersection(key):
            parts.append(f".{key}" if parts else key)
        else:
            parts.append("[" + key.replace("\\", "\\\\").replace("]", "\\]") + "]")
    return "".join(parts)
