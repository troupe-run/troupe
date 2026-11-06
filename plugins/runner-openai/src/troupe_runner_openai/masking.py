"""Keeping the credential out of everything the runner sends troupe (spec: openai-runner, "A
service's echo of the credential is masked"; openai-style-runner design D11).

The runner writes every message through one Mask, so events, transcript records, logs and errors
can't carry the credential however they were made. A service may also echo the key back with part
of it hidden, as OpenAI's 401 does (``sk-cana*********6789``); that form is masked too.
"""

import re
from collections.abc import Callable
from typing import Final

MASK: Final = "[credential]"
"""What the credential, or an echo of it, is replaced with."""

ENDS: Final = 4
"""How many of the credential's first or last characters identify a masked echo of it."""

SHORTEST_MATCHED_BY_ENDS: Final = 8
"""A credential shorter than this is masked only where it appears whole: four characters at either
end of a short value would match too much that isn't it."""

_TOKEN = re.compile(r"[^\s\"'<>(),;\\]+")
"""A run of characters an echoed key can be part of. Never a backslash, so an echo inside JSON text
(a transcript record holds a body as JSON) is masked without breaking the escape after it."""

_TRAILING = ".:"
"""Punctuation that ends a sentence after an echoed key, which isn't part of it."""

_CUT = "…"
"""What a cut text ends with (the SDK's ``cut`` and the exchange's), after the part it kept."""


class Mask:
    """Masks one credential in text. With no credential, text is unchanged."""

    def __init__(self, credential: str | None) -> None:
        self._credential = credential or None

    def __call__(self, text: str) -> str:
        credential = self._credential
        if credential is None:
            return text
        text = text.replace(credential, MASK)
        if len(credential) < SHORTEST_MATCHED_BY_ENDS:
            return text
        return _TOKEN.sub(
            lambda match: _cut_short(_echo(match.group(0), credential), credential), text
        )

    def json(self, value: object) -> object:
        """``value``, a decoded JSON value, with every string in it (keys included) masked."""
        return _walk(value, self)

    def __repr__(self) -> str:
        return "Mask(credential)" if self._credential else "Mask(None)"


def _echo(token: str, credential: str) -> str:
    """``token`` masked if it's an echo of ``credential`` with part of it hidden by ``*``."""
    core = token.rstrip(_TRAILING)
    if "*" in core and (core.startswith(credential[:ENDS]) or core.endswith(credential[-ENDS:])):
        return MASK + token[len(core) :]
    return token


def _cut_short(token: str, credential: str) -> str:
    """``token`` with the start of ``credential`` masked where it ends the token: a text cut to a
    limit inside the credential keeps only its start, which the whole-value match misses."""
    core = token.rstrip(_CUT + _TRAILING)
    for size in range(len(credential) - 1, SHORTEST_MATCHED_BY_ENDS - 1, -1):
        if core.endswith(credential[:size]):
            return core[: len(core) - size] + MASK + token[len(core) :]
    return token


def _walk(value: object, mask: Callable[[str], str]) -> object:
    if isinstance(value, str):
        return mask(value)
    if isinstance(value, list):
        return [_walk(item, mask) for item in value]
    if isinstance(value, dict):
        return {mask(key): _walk(item, mask) for key, item in value.items()}
    return value


__all__ = ["ENDS", "MASK", "SHORTEST_MATCHED_BY_ENDS", "Mask"]
