"""The actor schema's effect pattern and the SDK's accept exactly the same strings (spec: effects,
"A pattern that can't be meant is refused"; declared-effects design D1)."""

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from troupe.core import schemas
from troupe_plugin_sdk.effects import PatternError, pattern_regex

PATTERN = schemas.validator("https://troupe.run/protocol/effects.schema.json#/$defs/pattern")


def _schema_accepts(pattern: str) -> bool:
    return PATTERN.is_valid(pattern)


def _sdk_accepts(pattern: str) -> bool:
    try:
        pattern_regex(pattern)
    except PatternError:
        return False
    return True


# Parts close to the rules' edges, so generated patterns hit them often.
PARTS = st.one_of(
    st.sampled_from(
        ["**", "*", "?", ".", "..", "...", ".git", ".troupe", ".gitignore", "a**", "**b", "***", ""]
    ),
    st.text(alphabet="ab.*?:\\/\n\x7f é", min_size=0, max_size=4),
)
PATTERNS = st.one_of(
    st.lists(PARTS, min_size=1, max_size=4).map("/".join),
    st.text(max_size=12),
)


@settings(max_examples=2000)
@given(PATTERNS)
@example("**\n")
@example("out/**")
@example("/abs/**")
@example(".troupe")
@example(".troupe2/a")
@example("src/.git/x")
def test_the_schema_and_the_sdk_accept_or_refuse_each_pattern_alike(pattern: str) -> None:
    assert _schema_accepts(pattern) == _sdk_accepts(pattern), pattern


@pytest.mark.parametrize("pattern", ["out/**", "src/*.py", "a?c", "**", "docs/**/index.md", "é/x"])
def test_patterns_people_write_are_accepted_by_both(pattern: str) -> None:
    assert _schema_accepts(pattern)
    assert _sdk_accepts(pattern)


@pytest.mark.parametrize(
    "pattern",
    ["", "/abs", "a//b", "./a", "a/../b", "a\\b", "c:x", "a**", "a\tb", ".git/**", ".troupe/x"],
)
def test_patterns_that_cant_be_meant_are_refused_by_both(pattern: str) -> None:
    assert not _schema_accepts(pattern)
    assert not _sdk_accepts(pattern)
