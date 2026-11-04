"""Masking a run's credential (spec: runs, "troupe masks the credential in everything it keeps from
a run"; runtimes design D6)."""

import json

from hypothesis import example, given
from hypothesis import strategies as st

from troupe.core.masking import MARKER, Masker

KEY = "sk-test/abc+def=0123456789"
MASK = Masker(KEY)


def test_the_value_is_masked_in_text_and_bytes() -> None:
    assert MASK.text(f"Bearer {KEY}!") == f"Bearer {MARKER}!"
    assert MASK.bytes(f"x{KEY}y{KEY}".encode()) == f"x{MARKER}y{MARKER}".encode()


def test_the_json_escaped_forms_are_masked() -> None:
    escaped = json.dumps(KEY)
    assert MASK.text(escaped) == f'"{MARKER}"'
    assert MASK.text(KEY.replace("/", "\\/")) == MARKER


def test_a_value_with_a_quote_is_masked_in_json() -> None:
    masker = Masker('sk-"quoted"-0123')
    assert masker.text(json.dumps({"k": 'sk-"quoted"-0123'})) == json.dumps({"k": MARKER})


def test_a_non_ascii_value_is_masked_however_json_wrote_it() -> None:
    masker = Masker("sk-é-01234567")
    assert masker.text(json.dumps("sk-é-01234567")) == f'"{MARKER}"'
    assert masker.text(json.dumps("sk-é-01234567", ensure_ascii=False)) == f'"{MARKER}"'


def test_every_string_in_an_event_is_masked_keys_included() -> None:
    event = {"type": "log", "message": f"key {KEY}", "nested": [{KEY: KEY}], "seq": 3}
    assert MASK.data(event) == {
        "type": "log",
        "message": f"key {MARKER}",
        "nested": [{MARKER: MARKER}],
        "seq": 3,
    }


def test_no_credential_masks_nothing() -> None:
    assert Masker(None).text("anything [credential]") == "anything [credential]"
    stream = Masker(None).stream()
    assert stream.feed(b"abc") == b"abc"
    assert stream.finish() == b""


def test_a_key_split_across_two_reads_is_masked() -> None:
    stream = MASK.stream()
    half = len(KEY) // 2
    out = stream.feed(f"before {KEY[:half]}".encode()) + stream.feed(f"{KEY[half:]} after".encode())
    out += stream.finish()
    assert out == f"before {MARKER} after".encode()
    assert KEY[:half].encode() not in out
    assert KEY[half:].encode() not in out


TEXT = st.text(alphabet=st.sampled_from(list('ab/\\"sk-tes' + KEY[:5])), max_size=40)


@st.composite
def streams(draw: st.DrawFn) -> tuple[bytes, list[int]]:
    pieces = draw(st.lists(st.one_of(TEXT, st.just(KEY), st.just(json.dumps(KEY))), max_size=6))
    data = "".join(pieces).encode()
    cuts = sorted(draw(st.lists(st.integers(0, len(data)), max_size=5)))
    return data, cuts


@given(streams())
@example((f"{KEY}{KEY}".encode(), [len(KEY) - 1, len(KEY) + 1]))
def test_however_a_stream_is_chunked_it_masks_as_the_whole_does(
    case: tuple[bytes, list[int]],
) -> None:
    data, cuts = case
    stream = MASK.stream()
    out = b""
    start = 0
    for cut in [*cuts, len(data)]:
        out += stream.feed(data[start:cut])
        start = cut
    out += stream.finish()
    assert out == MASK.bytes(data)
    assert KEY.encode() not in out


@given(st.text(max_size=30), st.text(max_size=30))
def test_no_output_holds_the_value_whatever_surrounds_it(before: str, after: str) -> None:
    masked = MASK.text(before + KEY + after)
    assert KEY not in masked.replace(MARKER, "\0")
