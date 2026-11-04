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

import json
from dataclasses import dataclass, field

MARKER = "[credential]"
"""What a masked credential reads as."""


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
        """``text`` with every form of the value replaced."""
        if not self.forms:
            return text
        return self.bytes(text.encode("utf-8", "surrogatepass")).decode("utf-8", "surrogatepass")

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
