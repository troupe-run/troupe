"""Masking a transcript record that is JSON keeps it valid JSON (#438; spec: runs, "troupe masks
the credential in everything it keeps from a run"; transcript-masking design D1 to D5).

The property tests build a credential of visible ASCII, weighted toward the letters that end a JSON
escape and JSON's own syntax, and a record in one of the shapes runners send (JSON text, a ``data:``
line, JSON lines, an SSE event), whose strings hold pieces of the credential after every kind of
escape, and check what the run host keeps: still valid in its shape, no form of the credential in
it or in any string it decodes to outside ``[credential]``, and every value but a replaced one as
it was.
"""

import json
from dataclasses import dataclass

from hypothesis import example, given, settings
from hypothesis import strategies as st

from masking_checks import forms_outside_the_marker, writings
from troupe.core.masking import MARKER, Masker
from troupe.core.runners import host as host_module

REPLACED = MARKER
"""What a value that held the credential across JSON's syntax reads as once decoded (design D3)."""

ESCAPES = 'ntrbfu"\\/'
"""The characters a JSON escape ends with."""
SYNTAX = '",:[]{}'
"""JSON's own syntax, which a credential can hold and so span two values with."""
VISIBLE = st.characters(min_codepoint=0x21, max_codepoint=0x7E)


def _usable(credential: str) -> bool:
    """A credential whose forms don't hold a quote next to a bracket: troupe's own replacement,
    ``"[credential]"``, could complete one, so no replacement could be valid JSON (design,
    non-goals)."""
    return not any(b'"[' in form or b']"' in form for form in Masker(credential).forms)


credentials = st.text(
    st.sampled_from(ESCAPES + SYNTAX + "0123456789-") | VISIBLE, min_size=8, max_size=24
).filter(_usable)


@st.composite
def _strings(draw: st.DrawFn, credential: str) -> str:
    cut = draw(st.integers(0, len(credential)))
    piece = st.sampled_from(
        [
            *(credential, credential[:cut], credential[cut:], credential[1:]),
            *("\n", "\t", "\r", "\b", "\f", "\\", '"', "/", "\x00", "é", "\U0001f600", MARKER),
        ]
    ) | st.text(VISIBLE, max_size=3)
    return "".join(draw(st.lists(piece, max_size=5)))


def _values(credential: str) -> st.SearchStrategy[object]:
    numbers = st.integers(-(10**30), 10**30) | st.floats(allow_nan=False, allow_infinity=False)
    if credential.isdigit() or (credential[:1] == "-" and credential[1:].isdigit()):
        numbers = numbers | st.just(int(credential))
    leaves = _strings(credential) | numbers | st.booleans() | st.none()
    return st.recursive(
        leaves,
        lambda inner: (
            st.lists(inner, max_size=4)
            | st.lists(st.tuples(_strings(credential), inner), max_size=4).map(_Pairs)
        ),
        max_leaves=10,
    )


@dataclass(frozen=True)
class _Pairs:
    """An object as its key-value pairs, so a record can repeat a key, as JSON text may."""

    pairs: list[tuple[str, object]]


@st.composite
def _write(draw: st.DrawFn, value: object) -> str:
    """``value`` as JSON text, each character of each string written as any escape JSON allows for
    it (so a credential's letter can follow, or be, any escape), with random spacing."""
    space = draw(st.sampled_from(["", " ", "\n  "]))
    if isinstance(value, str):
        out = '"'
        for char in value:
            choices = [f"\\u{ord(char):04x}"] if ord(char) < 0x10000 else []
            if char == '"':
                choices.append('\\"')
            elif char == "\\":
                choices.append("\\\\")
            elif char in "\n\t\r\b\f":
                choices.append(json.dumps(char)[1:-1])
            elif ord(char) < 0x20:
                pass
            else:
                choices.append(char)
                if char == "/":
                    choices.append("\\/")
            if ord(char) >= 0x10000:
                choices.append(json.dumps(char)[1:-1])  # a surrogate pair
            out += draw(st.sampled_from(choices))
        return out + '"'
    if isinstance(value, list):
        items = [draw(_write(item)) for item in value]
        return "[" + space + ("," + space).join(items) + space + "]"
    if isinstance(value, _Pairs):
        items = [draw(_write(key)) + ":" + space + draw(_write(item)) for key, item in value.pairs]
        return "{" + space + ("," + space).join(items) + space + "}"
    return json.dumps(value)


@dataclass(frozen=True)
class Record:
    """A record a runner sends, and how to read back each JSON value in it."""

    text: str
    shape: str  # "json", "data", "lines" or "event"

    def values(self, stored: str) -> list[str]:
        """The JSON text of each value ``stored`` (this record, masked) holds."""
        if self.shape == "json":
            return [stored]
        if self.shape == "lines":
            return [line for line in stored.split("\n") if line.strip()]
        return [
            line.removeprefix("data:") for line in stored.split("\n") if line.startswith("data:")
        ]


@st.composite
def records(draw: st.DrawFn) -> tuple[str, Record, list[object]]:
    credential = draw(credentials)
    containers = _values(credential).filter(lambda v: isinstance(v, list | _Pairs))
    shape = draw(st.sampled_from(["json", "data", "lines", "event"]))
    values = draw(st.lists(containers, min_size=1, max_size=1 if shape != "lines" else 3))
    texts = [draw(_write(value)) for value in values]
    if shape == "json":
        text = draw(st.sampled_from(["", " ", "\n"])) + texts[0] + draw(st.sampled_from(["", "\n"]))
    elif shape == "data":
        text = "data:" + draw(st.sampled_from(["", " "])) + texts[0].replace("\n", " ")
    elif shape == "lines":
        text = "\n".join(t.replace("\n", " ") for t in texts) + draw(st.sampled_from(["", "\n"]))
    else:
        text = "event: message\ndata: " + texts[0].replace("\n", " ") + "\n\n"
    return credential, Record(text, shape), values


def _pairs(text: str) -> object:
    return json.loads(text, object_pairs_hook=_Pairs)


def _decoded_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [s for item in value for s in _decoded_strings(item)]
    if isinstance(value, _Pairs):
        return [s for key, item in value.pairs for s in [key, *_decoded_strings(item)]]
    return []


def _same_but_masked(masker: Masker, sent: object, kept: object) -> bool:
    """``kept`` is ``sent`` with each string masked as a string is, and at most some values (the
    smallest that held the credential across syntax) replaced by ``[credential]``."""
    if kept == REPLACED and sent != REPLACED:
        return True
    if isinstance(sent, str):
        return isinstance(kept, str) and kept == masker.text(sent)
    if isinstance(sent, list):
        return (
            isinstance(kept, list)
            and len(kept) == len(sent)
            and all(_same_but_masked(masker, s, k) for s, k in zip(sent, kept, strict=True))
        )
    if isinstance(sent, _Pairs):
        return (
            isinstance(kept, _Pairs)
            and len(kept.pairs) == len(sent.pairs)
            and all(
                _same_but_masked(masker, sk, kk) and _same_but_masked(masker, sv, kv)
                for (sk, sv), (kk, kv) in zip(sent.pairs, kept.pairs, strict=True)
            )
        )
    return kept == sent


def _check(credential: str, record: Record, kept: str) -> None:
    masker = Masker(credential)
    # Still valid in its shape: each JSON value in it parses.
    sent_values = [_pairs(text) for text in record.values(record.text)]
    kept_values = [_pairs(text) for text in record.values(kept)]
    # No form of the credential in the record, in any writing of it, or in any string it decodes to.
    for writing in writings(kept):
        assert not forms_outside_the_marker(masker, writing), (kept, writing)
    for value in kept_values:
        for string in _decoded_strings(value):
            for writing in writings(string):
                assert not forms_outside_the_marker(masker, writing), (kept, string)
    # Every value but a replaced one as it was, its strings masked as strings are.
    assert len(kept_values) == len(sent_values)
    for sent, value in zip(sent_values, kept_values, strict=True):
        assert _same_but_masked(masker, sent, value), (record.text, kept)
    # A record nothing in which holds the credential is kept byte for byte.
    clean = not any(
        form in writing
        for text in [record.text, *(s for v in sent_values for s in _decoded_strings(v))]
        for writing in writings(text)
        for form in masker.forms
    )
    if clean:
        assert kept == record.text


def _transcript_line(record: str, *, ascii_: bool) -> bytes:
    params = {"runId": "r", "record": record}
    message = {"jsonrpc": "2.0", "method": "run/transcript", "params": params}
    return json.dumps(message, ensure_ascii=ascii_).encode()


ISSUE_EXAMPLE: tuple[str, Record, list[object]] = (
    "nsecret-token-0123456789",
    Record('{"type":"assistant","text":"key:\\nsecret-token-0123456789"}', "json"),
    [],
)


@settings(max_examples=500, deadline=None)
@given(records(), st.booleans())
@example(ISSUE_EXAMPLE, False)
@example(
    ("nsecret-token-0123456789", Record('data: {"t":"a\\nsecret-token-0123456789"}', "data"), []),
    False,
)
@example(("u0041bcdefgh", Record('{"t":"\\u0041bcdefgh"}', "json"), []), False)
@example(('ab","cdefg', Record('[1,["xab","cdefgy"],2]', "json"), []), True)
def test_a_text_record_that_is_json_is_kept_valid_with_no_form_of_the_credential(
    case: tuple[str, Record, list[object]], ascii_: bool
) -> None:
    credential, record, _ = case
    message, _line = host_module.parse_runner_line(
        Masker(credential), _transcript_line(record.text, ascii_=ascii_), 1
    )
    assert isinstance(message, dict)
    kept = message["params"]["record"]
    _check(credential, record, kept)


@settings(max_examples=300, deadline=None)
@given(records())
@example(ISSUE_EXAMPLE)
def test_a_base64_record_that_is_json_is_kept_valid_with_no_form_of_the_credential(
    case: tuple[str, Record, list[object]],
) -> None:
    credential, record, _ = case
    kept = Masker(credential).record_bytes(record.text.encode("utf-8"))
    _check(credential, record, kept.decode("utf-8"))
