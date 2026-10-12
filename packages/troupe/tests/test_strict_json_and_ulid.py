"""Strict JSON and monotonic ULIDs (event-store design D3, D4)."""

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
