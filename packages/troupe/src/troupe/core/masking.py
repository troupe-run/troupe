"""Masking a run's credential in everything troupe keeps from it (spec: runs, "troupe masks the
credential in everything it keeps from a run"; runtimes design D6).

The runner contract says a runner never sends its credential back. troupe doesn't rely on that:
the run host masks the value in each run event, transcript record and byte of standard error
before anything is stored or sent on, and in any error. Each form the value can take in text is
replaced with ``[credential]``: its UTF-8 bytes, and its JSON-escaped forms (as ``json.dumps``
writes it, with and without non-ASCII escaped, and with ``/`` as ``\\/``).

A transcript record is masked by its shape (``Masker.record``; transcript-masking design, #438):
a record that is JSON text, or whose lines are JSON or ``data:`` lines holding JSON, has its
strings and numbers masked in place, so it stays valid JSON; any other record is masked as a
string.

Standard error arrives in chunks, so a value can be split across two reads. ``StreamMask`` holds
back the bytes at the end of each chunk that could be the start of a value, and lets them go once
the next chunk shows they aren't, or at the end.
"""

import bisect
import builtins
import json
import re
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

    def record(self, text: str) -> str:
        """A transcript record's text masked so it stays valid in its own shape (transcript-masking
        design D1 to D3, #438). A record that is JSON text, or whose lines are JSON or ``data:``
        lines holding JSON, has each string and number that holds a form masked in place, and a
        form left across JSON's syntax replaces the smallest value that holds it with
        ``"[credential]"``; every other byte is kept. Any other record is masked as ``text``."""
        if not self.forms or not (self._holds_a_form(text) or _ASCII_ESCAPE.search(text)):
            return text
        pieces = _record_pieces(text)
        if pieces is None:
            return self.text(text)
        for piece in pieces:
            if piece.kind == "json":
                piece.text = self._mask_tokens(piece.text)
            elif piece.kind == "text":
                piece.text = self.text(piece.text)
        return self._mask_across_values(pieces)

    def record_bytes(self, data: builtins.bytes) -> builtins.bytes:
        """A base64 transcript record's bytes masked: as ``record`` when they're UTF-8 text in one
        of the JSON shapes it keeps valid, else as ``bytes`` (design D4)."""
        if not self.forms:
            return data
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return self.bytes(data)
        if _record_pieces(text) is None:
            return self.bytes(data)
        return self.record(text).encode("utf-8", "surrogatepass")

    def _mask_tokens(self, value: str) -> str:
        """JSON text ``value`` with each string that masks differently, or whose own writing holds
        a form, rewritten masked, and each number or literal that holds a form made
        ``"[credential]"`` (design D2). Everything else is kept byte for byte."""
        out: list[str] = []
        done = 0
        for match in _JSON_TOKEN.finditer(value):
            lexeme = match.group()
            if lexeme in "[]{}":
                continue
            raw_holds = any(form in _raw(lexeme) for form in self.forms)
            if lexeme[0] == '"':
                decoded = json.loads(lexeme)
                masked = self.text(decoded)
                if masked == decoded and not raw_holds:
                    continue
                written = json.dumps(masked, ensure_ascii=_has_lone_surrogate(masked))
                if written == lexeme:
                    continue
            elif raw_holds:
                written = _QUOTED_MARKER
            else:
                continue
            out += [value[done : match.start()], written]
            done = match.end()
        return "".join([*out, value[done:]])

    def _mask_across_values(self, pieces: list["_Piece"]) -> str:
        """The record put back together, with each form still left (only across JSON's syntax)
        replacing the smallest value that holds it, else its lines' values (design D3). Each pass
        replaces every covered run it finds, so a record costs a few passes however many runs it
        holds (review of #439)."""
        while True:
            text = "".join(piece.text for piece in pieces)
            if not self._holds_a_form(text):
                return text
            runs = self._covered_runs(text)
            if not runs:
                return text
            if not _replace_runs(pieces, runs):
                # Nothing left to replace but troupe's own text, a line break or a prefix: the
                # whole record becomes the marker, a lone data line keeping its field name. Only
                # a credential holding troupe's own replacement can still be covered then, and
                # masking it as text keeps it out (design, non-goals).
                first = pieces[0]
                one_data_line = first.text.startswith("data:") and "\n" not in text
                return self.text((first.text if one_data_line else "") + _QUOTED_MARKER)

    def _covered_runs(self, text: str) -> list[tuple[int, int]]:
        """Each maximal run of characters of ``text`` that a form covers, in some writing,
        outside any ``[credential]`` in it, as character offsets, in order."""
        units: list[str | None] = []
        offsets: list[int] = []
        at = 0
        while at < len(text):
            offsets.append(at)
            if text.startswith(MARKER, at):
                units.append(None)
                at += len(MARKER)
            else:
                units.append(text[at])
                at += 1
        runs: list[tuple[int, int]] = []
        for index in sorted(self._covered(units)):
            start = offsets[index]
            end = start + (len(MARKER) if units[index] is None else 1)
            if runs and runs[-1][1] == start:
                runs[-1] = (runs[-1][0], end)
            else:
                runs.append((start, end))
        return runs

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


_QUOTED_MARKER = json.dumps(MARKER)
"""What a JSON value that held the credential across JSON's syntax becomes (design D3)."""

_JSON_TOKEN = re.compile(
    r'"(?:[^"\\]|\\.)*"|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|true|false|null|[\[\]{}]'
)
"""A token of JSON text that's already known to be valid: a string, a number, a literal, or a
bracket. Scanned left to right, a string is matched whole, so nothing inside one is taken for
another token."""

_ASCII_ESCAPE = re.compile(r"\\u00[2-7][0-9A-Fa-f]")
"""A ``\\u`` escape of a visible ASCII character, which can spell a credential's character where
no writing of the record shows it. JSON writers escape only control characters and, when asked,
non-ASCII ones, so a record without one, and without a form in some writing, is left as it is
(design D1)."""

_DATA_LINE = re.compile(r"data: ?")
"""A server-sent-events data field's name, with the one space the format allows after it."""


@dataclass
class _Piece:
    """A part of a record: ``json`` (one JSON object or array), ``text`` (a line that isn't), or
    ``fixed`` (whitespace, a line break, a ``data:`` prefix), and the line it's on."""

    kind: str
    text: str
    line: int


def _is_json_container(text: str) -> bool:
    """Whether ``text`` is one JSON object or array, with optional whitespace round it. NaN and
    Infinity aren't JSON; a duplicate key is valid JSON text, kept as it is."""
    stripped = text.strip(" \t\r\n")
    if not stripped or stripped[0] not in "[{":
        return False
    try:
        json.loads(stripped, parse_constant=_not_json)
    except (ValueError, RecursionError):
        return False
    return True


def _not_json(constant: str) -> object:
    raise ValueError(f"{constant} isn't JSON")


def _json_pieces(text: str, line: int, prefix: str = "") -> list[_Piece]:
    body = text[len(prefix) :]
    start = len(body) - len(body.lstrip(" \t\r\n"))
    end = len(body.rstrip(" \t\r\n"))
    pieces = [
        _Piece("fixed", prefix + body[:start], line),
        _Piece("json", body[start:end], line),
        _Piece("fixed", body[end:], line),
    ]
    return [piece for piece in pieces if piece.text or piece.kind == "json"]


def _record_pieces(text: str) -> list[_Piece] | None:
    """``text`` split into its pieces, or None when no part of it is JSON (design D1): the whole
    record when it's one JSON object or array, else each line, as a JSON line, a ``data:`` line
    holding JSON, or text."""
    if _is_json_container(text):
        return _json_pieces(text, 0)
    pieces: list[_Piece] = []
    found = False
    for number, line in enumerate(text.split("\n")):
        if number:
            pieces.append(_Piece("fixed", "\n", number))
        data = _DATA_LINE.match(line)
        if _is_json_container(line):
            pieces += _json_pieces(line, number)
            found = True
        elif data is not None and _is_json_container(line[data.end() :]):
            pieces += _json_pieces(line, number, data.group())
            found = True
        elif line:
            pieces.append(_Piece("text", line, number))
    return pieces if found else None


def _value_spans(value: str) -> list[tuple[int, int]]:
    """The span of every value in JSON text ``value`` (keys included), inner before outer."""
    spans: list[tuple[int, int]] = []
    opened: list[int] = []
    for match in _JSON_TOKEN.finditer(value):
        lexeme = match.group()
        if lexeme in "[{":
            opened.append(match.start())
        elif lexeme in "]}":
            spans.append((opened.pop(), match.end()))
        else:
            spans.append((match.start(), match.end()))
    return spans


def _replace_runs(pieces: list[_Piece], runs: list[tuple[int, int]]) -> bool:
    """Replace what holds each covered run (offsets into the joined pieces): the smallest value
    holding it when it lies in one JSON piece, else every JSON value on the lines it touches, and
    the covered characters of text lines. False when that changes nothing."""
    starts: list[int] = []
    at = 0
    for piece in pieces:
        starts.append(at)
        at += len(piece.text)
    in_json: dict[int, list[tuple[int, int]]] = {}  # a JSON piece's runs, in its own offsets
    in_text: dict[int, list[tuple[int, int]]] = {}
    whole_lines: set[int] = set()
    for start, end in runs:
        touched = [
            (
                index,
                max(start, starts[index]) - starts[index],
                min(end, starts[index] + len(piece.text)) - starts[index],
            )
            for index, piece in enumerate(pieces)
            if max(start, starts[index]) < min(end, starts[index] + len(piece.text))
        ]
        if len(touched) == 1 and pieces[touched[0][0]].kind == "json":
            index, low, high = touched[0]
            in_json.setdefault(index, []).append((low, high))
            continue
        whole_lines.update(pieces[index].line for index, _, _ in touched)
        for index, low, high in touched:
            if pieces[index].kind == "text":
                in_text.setdefault(index, []).append((low, high))
    changed = False
    for index, piece_runs in in_json.items():
        piece = pieces[index]
        if piece.line in whole_lines:
            continue
        targets = _smallest_values(piece.text, piece_runs)
        if targets is None:
            whole_lines.add(piece.line)
            continue
        for begin, finish in reversed(targets):
            piece.text = piece.text[:begin] + _QUOTED_MARKER + piece.text[finish:]
        changed = True
    for piece in pieces:
        if piece.kind == "json" and piece.line in whole_lines and piece.text != _QUOTED_MARKER:
            piece.text = _QUOTED_MARKER
            changed = True
    for index, piece_runs in in_text.items():
        piece = pieces[index]
        for low, high in reversed(piece_runs):
            piece.text = piece.text[:low] + MARKER + piece.text[high:]
        changed = True
    return changed


def _smallest_values(value: str, runs: list[tuple[int, int]]) -> list[tuple[int, int]] | None:
    """For JSON text ``value`` and runs within it (in order), the smallest value holding each run,
    with any held by another dropped, in order; None when one is held only by a value that is
    already ``"[credential]"``. One sweep over the values, so many runs cost one scan."""
    spans = sorted(_value_spans(value), key=lambda span: (span[0], -span[1]))
    open_spans: list[tuple[int, int]] = []  # nested, outermost first
    next_span = 0
    chosen: list[tuple[int, int]] = []
    for low, high in runs:
        while next_span < len(spans) and spans[next_span][0] <= low:
            span = spans[next_span]
            while open_spans and open_spans[-1][1] <= span[0]:
                open_spans.pop()
            open_spans.append(span)
            next_span += 1
        while open_spans and open_spans[-1][1] <= low:
            open_spans.pop()
        holder = next((span for span in reversed(open_spans) if span[1] >= high), None)
        if holder is None or value[holder[0] : holder[1]] == _QUOTED_MARKER:
            return None
        chosen.append(holder)
    kept: list[tuple[int, int]] = []
    for begin, finish in sorted(set(chosen), key=lambda span: (span[0], -span[1])):
        if kept and begin < kept[-1][1]:
            continue  # inside a value already being replaced
        kept.append((begin, finish))
    return kept


def _has_lone_surrogate(text: str) -> bool:
    return any("\ud800" <= char <= "\udfff" for char in text)


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
