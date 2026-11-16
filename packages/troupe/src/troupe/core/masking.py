"""Masking a run's credential in everything troupe keeps from it (spec: runs, "troupe masks the
credential in everything it keeps from a run"; runtimes design D6).

The runner contract says a runner never sends its credential back. troupe doesn't rely on that:
the run host masks the value in each run event, transcript record and byte of standard error
before anything is stored or sent on, and in any error. Each form the value can take in text is
replaced with ``[credential]``: its UTF-8 bytes, and its JSON-escaped forms (as ``json.dumps``
writes it, with and without non-ASCII escaped, and with ``/`` as ``\\/``).

Standard error arrives in chunks, so a value can be split across two reads. ``StreamMask`` holds
back the bytes at the end of each chunk that could be the start of a value, and lets them go once
the next chunk shows they aren't, or at the end.
"""

import bisect
import json
from collections.abc import Callable
from dataclasses import dataclass, field

MARKER = "[credential]"
"""What a masked credential reads as."""

WINDOW_CHARS = 4096
"""How many characters of a large string the escape-aware pass checks at a time: only a window
that can hold a form of the value is masked a character at a time."""


@dataclass(frozen=True)
class Masker:
    """Masks one run's credential. With no credential it masks nothing."""

    value: str | None = None
    forms: tuple[bytes, ...] = field(init=False)

    def __post_init__(self) -> None:
        found: set[bytes] = set()
        if self.value:
            for text in (
                self.value,
                json.dumps(self.value)[1:-1],
                json.dumps(self.value, ensure_ascii=False)[1:-1],
            ):
                found.add(text.encode("utf-8"))
                found.add(text.replace("/", "\\/").encode("utf-8"))
        # Longest first, so a form that holds another is replaced whole.
        object.__setattr__(self, "forms", tuple(sorted(found, key=lambda f: (-len(f), f))))

    @property
    def longest(self) -> int:
        return len(self.forms[0]) if self.forms else 0

    def bytes(self, data: bytes) -> bytes:
        """``data`` with every form of the value replaced."""
        if not self.forms:
            return data
        out, rest = _replace_complete(data, self.forms)
        return out + rest

    def text(self, text: str) -> str:
        """``text`` with every form of the value replaced, in it and in the JSON text written for it
        (host-robustness design D2). A form that only appears once the string is written as JSON
        (a newline, written ``\\n``, before the rest of a value that starts with ``n``) is replaced
        too, with the characters whose writing it covers, so neither the string nor any JSON text
        troupe writes for it holds the value outside ``[credential]``."""
        if not self.forms or not self._holds_a_form(text):
            return text
        if len(text) <= WINDOW_CHARS:
            return self._mask_units(text)
        # A form spans at most as many characters as it has bytes, so every form that covers a
        # character lies within that many characters of it. Only the windows that can hold one
        # (checked at C speed) get the per-character pass, so a large string costs little more
        # than a bytes.replace (review of #437).
        margin = self.longest
        hot: list[tuple[int, int]] = []
        for start in range(0, len(text), WINDOW_CHARS):
            low, high = max(0, start - margin), min(len(text), start + WINDOW_CHARS + margin)
            if self._holds_a_form(text[low:high]):
                if hot and low <= hot[-1][1]:
                    hot[-1] = (hot[-1][0], high)
                else:
                    hot.append((low, high))
        pieces: list[str] = []
        done = 0
        for low, high in hot:
            pieces += [text[done:low], self._mask_units(text[low:high])]
            done = high
        masked = "".join([*pieces, text[done:]])
        # A marker put at a region's edge could complete a form with what's past it; if anything
        # is left, mask the whole string the slow way, which handles that.
        return masked if not self._holds_a_form(masked) else self._mask_units(text)

    def _holds_a_form(self, text: str) -> bool:
        return any(form in writing for writing in _writings(text) for form in self.forms)

    def _mask_units(self, text: str) -> str:
        """``text`` masked a character at a time: each run of characters some form covers, in
        any writing, becomes one marker, repeated until no form covers a character."""
        units: list[str | None] = list(text)  # None is a [credential] troupe put there
        while True:
            covered = self._covered(units)
            if not covered:
                return "".join(MARKER if unit is None else unit for unit in units)
            merged: list[str | None] = []
            for index, unit in enumerate(units):
                if index not in covered:
                    merged.append(unit)
                elif index == 0 or index - 1 not in covered:
                    merged.append(None)
            units = merged

    def _covered(self, units: list[str | None]) -> set[int]:
        """The units that some form of the value in some writing of ``units`` covers, for each form
        that covers at least one character the runner sent. A form wholly inside markers is
        troupe's own text, and covers nothing. Each pass that covers something replaces at least
        one character, so masking ends."""
        marker = MARKER.encode("utf-8")
        covered: set[int] = set()
        for write in _WRITERS:
            pieces = [marker if unit is None else write(unit) for unit in units]
            starts: list[int] = []
            joined = bytearray()
            for piece in pieces:
                starts.append(len(joined))
                joined += piece
            ends = [start + len(piece) for start, piece in zip(starts, pieces, strict=True)]
            for form in self.forms:
                at = joined.find(form)
                while at != -1:
                    first = bisect.bisect_right(starts, at) - 1
                    last = bisect.bisect_left(ends, at + len(form))
                    span = range(first, last + 1)
                    if any(units[index] is not None for index in span):
                        covered.update(span)
                    at = joined.find(form, at + 1)
        return covered

    def data(self, value: object) -> object:
        """A JSON value with every string in it, keys included, masked."""
        if not self.forms:
            return value
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self.data(item) for item in value]
        if isinstance(value, dict):
            return {self.text(str(key)): self.data(item) for key, item in value.items()}
        return value

    def stream(self) -> "StreamMask":
        """A mask for a stream of chunks, such as standard error."""
        return StreamMask(self)


def _raw(text: str) -> bytes:
    return text.encode("utf-8", "surrogatepass")


def _json_kept(text: str) -> bytes:
    return json.dumps(text, ensure_ascii=False)[1:-1].encode("utf-8", "surrogatepass")


def _json_escaped(text: str) -> bytes:
    return json.dumps(text)[1:-1].encode("ascii")


_WRITERS: tuple[Callable[[str], bytes], ...] = (_raw, _json_kept, _json_escaped)
"""The texts a string can be written as: itself, and JSON with non-ASCII kept and escaped. JSON
writes a string a character at a time, so a string's writing is its characters' writings joined."""


def _writings(text: str) -> list[bytes]:
    return [write(text) for write in _WRITERS]


def _replace_complete(data: bytes, forms: tuple[bytes, ...]) -> tuple[bytes, bytes]:
    """``data`` with every complete form replaced, as what's done and what's left after the last
    replacement (which holds no complete form)."""
    marker = MARKER.encode("utf-8")
    out = bytearray()
    rest = data
    while True:
        best: tuple[int, int] | None = None
        for form in forms:
            at = rest.find(form)
            if at != -1 and (
                best is None or at < best[0] or (at == best[0] and len(form) > best[1])
            ):
                best = (at, len(form))
        if best is None:
            return bytes(out), rest
        at, length = best
        out += rest[:at] + marker
        rest = rest[at + length :]


class StreamMask:
    """Masks a stream given in chunks, a value split across chunks included."""

    def __init__(self, masker: Masker) -> None:
        self._masker = masker
        self._held = b""

    def feed(self, chunk: bytes) -> bytes:
        """What of the stream so far can be let go, masked."""
        if not self._masker.forms:
            return chunk
        done, rest = _replace_complete(self._held + chunk, self._masker.forms)
        keep = self._masker.longest - 1
        cut = max(len(rest) - keep, 0)
        self._held = rest[cut:]
        return done + rest[:cut]

    def finish(self) -> bytes:
        """The rest of the stream, at its end."""
        held, self._held = self._held, b""
        return held
