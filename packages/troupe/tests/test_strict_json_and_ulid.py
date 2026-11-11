"""Strict JSON and monotonic ULIDs (event-store design D3, D4)."""

import json
import json.decoder
import json.scanner
import math
import re

import pytest
from hypothesis import given
from hypothesis import strategies as st

from troupe.core import strict_json
from troupe.core.ulid import new_ulid

JSON_VALUES = st.recursive(
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(),
    lambda inner: st.lists(inner) | st.dictionaries(st.text(), inner),
    max_leaves=20,
)


@given(JSON_VALUES)
def test_canonical_json_reads_back_to_the_same_value(value: object) -> None:
    assert strict_json.loads(strict_json.dumps(value)) == value


@pytest.mark.parametrize(
    "text",
    [
        '{"a": 1, "a": 2}',
        '{"outer": {"b": 1, "b": 1}}',
        '[{"x": 1, "y": 2, "x": 3}]',
        '{"v": NaN}',
        '{"v": Infinity}',
        '{"v": -Infinity}',
        "[NaN]",
        "{not json",
        b"\xff\xfe",
    ],
)
def test_duplicate_keys_non_finite_numbers_and_non_json_are_refused(text: str | bytes) -> None:
    with pytest.raises(strict_json.StrictJSONError):
        strict_json.loads(text)


def test_canonical_json_refuses_to_write_non_finite_numbers() -> None:
    with pytest.raises(ValueError, match="JSON compliant"):
        strict_json.dumps({"v": math.nan})


def test_canonical_json_sorts_keys_has_no_spaces_and_keeps_unicode() -> None:
    assert strict_json.dumps({"b": 1, "a": "é"}) == '{"a":"é","b":1}'


def test_ulids_are_26_crockford_characters_and_strictly_increasing() -> None:
    made = [new_ulid() for _ in range(10_000)]
    assert all(re.fullmatch(r"[0-9A-HJKMNP-TV-Z]{26}", ulid) for ulid in made)
    assert made == sorted(made)
    assert len(set(made)) == len(made)


# A refusal's rule holds none of the text (config-set-json-redacts design D2).

CANARY = "q7ZxW9pL4vR2canary"

BROKEN = [
    pytest.param(f'"{CANARY}', id="an unterminated string"),
    pytest.param(f'{{"{CANARY}" 1}}', id="a key with no colon"),
    pytest.param(f'["{CANARY}",]', id="a trailing comma"),
    pytest.param(f'"{CANARY}" {CANARY}', id="extra data"),
    pytest.param(f'"{CANARY}\\q"', id="a bad escape"),
    pytest.param(f'"{CANARY}\\u12"', id="a bad unicode escape"),
    pytest.param(f'"{CANARY}\x01"', id="a control character"),
    pytest.param(f"https://user:{CANARY}@example.com/v1", id="not JSON at all"),
    pytest.param(f'{{"{CANARY}": 1, "{CANARY}": 2}}', id="a repeated key"),
    pytest.param(f'{{"a": 1, "a": "{CANARY}"}}', id="a repeated key's value"),
    pytest.param(f'["{CANARY}", NaN]', id="NaN"),
]


def _refusal(text: str | bytes) -> strict_json.StrictJSONError:
    with pytest.raises(strict_json.StrictJSONError) as caught:
        strict_json.loads(text)
    return caught.value


@pytest.mark.parametrize("text", BROKEN)
def test_a_refusals_rule_holds_none_of_the_text(text: str) -> None:
    refused = _refusal(text)
    assert refused.rule
    assert CANARY not in refused.rule
    assert "example.com" not in refused.rule


@pytest.mark.parametrize("text", BROKEN)
def test_the_pure_python_decoders_rule_holds_none_of_the_text_either(
    text: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Its bad-escape message adds the escaped character, which the C decoder's doesn't.
    # typeshed doesn't list the pure-Python versions, so they're looked up by name.
    monkeypatch.setattr(json.decoder, "scanstring", getattr(json.decoder, "py_scanstring"))  # noqa: B009
    monkeypatch.setattr(json.scanner, "make_scanner", getattr(json.scanner, "py_make_scanner"))  # noqa: B009
    refused = _refusal(text)
    assert CANARY not in refused.rule
    assert "\\q" not in refused.rule
    assert "'q'" not in refused.rule


def _rule_of(text: str) -> str | None:
    try:
        strict_json.loads(text)
    except strict_json.StrictJSONError as refused:
        return refused.rule
    return None


@given(st.text(min_size=1, max_size=40))
def test_any_refused_text_holding_a_canary_gives_a_rule_without_it(text: str) -> None:
    for broken in (f'"{CANARY}{text}', f'{{"{CANARY}": {text}', f"{text}{CANARY}"):
        assert CANARY not in (_rule_of(broken) or "")


def test_a_refusal_says_where_the_json_stopped_making_sense() -> None:
    refused = _refusal('{\n  "a": 1,\n  "b" 2\n}')
    assert (refused.rule, refused.line, refused.column) == ("Expecting ':' delimiter", 3, 7)


def test_a_repeated_keys_rule_names_no_key_and_no_position() -> None:
    refused = _refusal('{"secret-key": 1, "secret-key": 2}')
    assert refused.rule == "a key appears more than once in one object"
    assert (refused.line, refused.column) == (None, None)


def test_bytes_that_arent_text_say_which_byte() -> None:
    refused = _refusal(b'{"a": "\xff"}')
    assert refused.rule == "its bytes can't be read as text (at byte 8)"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('{"a": 1, "a": 2}', "the key 'a' appears more than once in one object"),
        ('{"v": NaN}', "NaN isn't a JSON number"),
        (
            "{not json",
            "Expecting property name enclosed in double quotes: line 1 column 2 (char 1)",
        ),
    ],
)
def test_the_message_for_troupes_own_files_is_unchanged(text: str, message: str) -> None:
    assert str(_refusal(text)) == message
