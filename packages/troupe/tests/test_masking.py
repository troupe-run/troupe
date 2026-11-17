"""Masking a run's credential (spec: runs, "troupe masks the credential in everything it keeps from
a run"; runtimes design D6)."""

import json

from hypothesis import example, given, settings
from hypothesis import strategies as st

from masking_checks import forms_outside_the_marker, writings
from troupe.core.masking import MARKER, WINDOW_CHARS, Masker

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


# Escape-aware masking of a string (host-robustness D2, #330)

VISIBLE = st.characters(min_codepoint=0x21, max_codepoint=0x7E)
"""A credential's characters: visible ASCII (troupe_plugin_sdk.credential.well_formed)."""


@st.composite
def credentials_and_strings(draw: st.DrawFn) -> tuple[str, str]:
    credential = draw(st.text(VISIBLE, min_size=1, max_size=12))
    cut = draw(st.integers(0, len(credential)))
    fragments = st.sampled_from(
        [
            credential,
            credential[:cut],
            credential[cut:],
            credential[1:],
            "\n",
            "\\",
            '"',
            "/",
            "é",
            "\U0001f600",
            "\x00",
            MARKER,
        ]
    ) | st.text(VISIBLE, max_size=4)
    return credential, "".join(draw(st.lists(fragments, max_size=8)))


@given(credentials_and_strings())
@example(("nsecret-token-0123456789", "\nsecret-token-0123456789"))
@example(("abc", "\nb\u000abc"))
@example(("]x", "x]xx"))
@example(("u00e9", "é"))
@example(("dent", MARKER))
def test_no_writing_of_a_masked_string_holds_the_credential_outside_the_marker(
    case: tuple[str, str],
) -> None:
    credential, text = case
    masker = Masker(credential)
    masked = masker.text(text)
    for writing in writings(masked):
        assert forms_outside_the_marker(masker, writing) == [], (masked, writing)


@given(credentials_and_strings())
def test_a_string_no_writing_of_which_holds_the_credential_is_unchanged(
    case: tuple[str, str],
) -> None:
    credential, text = case
    masker = Masker(credential)
    if not any(form in writing for writing in writings(text) for form in masker.forms):
        assert masker.text(text) == text


def test_a_newline_before_the_rest_of_a_credential_starting_with_n_is_masked_with_it() -> None:
    masker = Masker("nsecret-token-0123456789")
    assert masker.text("key: \nsecret-token-0123456789.") == "key: [credential]."
    assert masker.data({"\nsecret-token-0123456789": ["\nsecret-token-0123456789"]}) == {
        MARKER: [MARKER]
    }


@st.composite
def large_strings(draw: st.DrawFn) -> tuple[str, str]:
    """A credential and a string past one window, its pieces placed so some straddle a window's
    edge (WINDOW_CHARS), where only the windows that can hold a form get the per-character pass."""
    credential, text = draw(credentials_and_strings())
    pieces = draw(st.lists(st.sampled_from([text, credential, "\n" + credential[1:]]), max_size=4))
    out = ""
    for piece in pieces:
        out += "y" * draw(st.integers(0, WINDOW_CHARS + 50)) + piece
    return credential, out + "z" * WINDOW_CHARS


@settings(max_examples=200, deadline=None)
@given(large_strings())
def test_a_large_masked_string_holds_the_credential_nowhere_outside_the_marker(
    case: tuple[str, str],
) -> None:
    credential, text = case
    masker = Masker(credential)
    masked = masker.text(text)
    for writing in writings(masked):
        assert forms_outside_the_marker(masker, writing) == []
    if not any(form in writing for writing in writings(text) for form in masker.forms):
        assert masked == text


# A transcript record that is JSON stays JSON (transcript-masking design D1 to D4, #438)

ESCAPE_KEY = "nsecret-token-0123456789"
"""A credential that starts with n, the letter JSON's escape for a newline ends with."""


def test_a_record_that_is_json_with_an_escape_before_the_credential_stays_json() -> None:
    record = '{"type":"assistant","text":"key:\\nsecret-token-0123456789"}'
    masked = Masker(ESCAPE_KEY).record(record)
    assert masked == '{"type":"assistant","text":"key:[credential]"}'
    json.loads(masked)


def test_a_record_keeps_its_spacing_duplicate_keys_and_numbers_byte_for_byte() -> None:
    record = (
        '{ "a" : 1.50, "a":2,\n  "t": "x\\u00e9\\nsecret-token-0123456789", "b": [true, null] }'
    )
    masked = Masker(ESCAPE_KEY).record(record)
    assert masked == '{ "a" : 1.50, "a":2,\n  "t": "xé[credential]", "b": [true, null] }'


def test_a_number_that_holds_the_credential_becomes_the_marker_string() -> None:
    masked = Masker("12345678").record('{"n": 9123456789, "m": 1.5}')
    assert masked == '{"n": "[credential]", "m": 1.5}'


def test_a_lone_surrogate_escape_in_a_masked_string_stays_an_escape() -> None:
    masked = Masker(ESCAPE_KEY).record('["\\ud800\\nsecret-token-0123456789"]')
    assert masked == '["\\ud800[credential]"]'
    masked.encode("utf-8")


def test_a_credential_across_two_values_replaces_the_smallest_value_holding_it() -> None:
    masked = Masker('ab","cdefg').record('{"keep": [1, 2], "x": [1,["xab","cdefgy"],2]}')
    assert masked == '{"keep": [1, 2], "x": [1,"[credential]",2]}'


def test_a_credential_reaching_into_a_data_lines_field_name_replaces_the_lines_value() -> None:
    assert Masker('ta: {"ke').record('data: {"key":1}') == 'data: "[credential]"'


def test_a_streamed_data_line_is_masked_as_json() -> None:
    masked = Masker(ESCAPE_KEY).record('data: {"delta":"\\nsecret-token-0123456789"}')
    assert masked == 'data: {"delta":"[credential]"}'


def test_only_the_json_line_that_held_the_credential_changes() -> None:
    record = '{"a":"\\t"}\n{"b":"\\nsecret-token-0123456789"}\n["c"]\n'
    masked = Masker(ESCAPE_KEY).record(record)
    assert masked == '{"a":"\\t"}\n{"b":"[credential]"}\n["c"]\n'


def test_an_sse_event_masks_its_data_line_and_keeps_the_rest() -> None:
    record = 'event: delta\ndata: {"t":"\\nsecret-token-0123456789"}\n\n'
    masked = Masker(ESCAPE_KEY).record(record)
    assert masked == 'event: delta\ndata: {"t":"[credential]"}\n\n'


def test_a_record_that_isnt_json_is_masked_as_a_string_is() -> None:
    text = "key:\nsecret-token-0123456789 and more"
    assert Masker(ESCAPE_KEY).record(text) == Masker(ESCAPE_KEY).text(text)
    assert Masker(ESCAPE_KEY).record("12345678") == "12345678"
    assert Masker("12345678").record("12345678") == MARKER


def test_a_record_that_cant_hold_the_credential_is_returned_as_it_is() -> None:
    record = '{"t":"\\n plain"}'
    assert Masker(ESCAPE_KEY).record(record) is record


def test_a_base64_record_is_masked_as_json_only_when_it_is_json_text() -> None:
    masker = Masker(ESCAPE_KEY)
    assert masker.record_bytes(b'{"t":"\\nsecret-token-0123456789"}') == b'{"t":"[credential]"}'
    for data in (b"\xff\\nsecret-token-0123456789", b"x\\nsecret-token-0123456789"):
        assert masker.record_bytes(data) == masker.bytes(data)
