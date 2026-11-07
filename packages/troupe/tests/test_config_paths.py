"""Config paths as people type and read them (spec: config, "A config path can put any key in
brackets", "A config path is shown in the form it is typed", "A malformed config path is refused";
config-path-dotted-keys design D2, D3, D6).

The first two properties pin what the reader accepted before brackets existed: written against
``troupe.cli.values.split_path`` and passing there before the reader changed (task 1.1), so the new
reader can't quietly break a path that already worked.
"""

from hypothesis import given
from hypothesis import strategies as st

from troupe.cli.values import split_path

read = split_path

PLAIN = st.text(st.characters(codec="utf-8", exclude_characters=".[]=\\"), min_size=1)
"""A key the old reader could read: non-empty, and holding none of ``. [ ] = \\``."""


TEXT = st.text(st.characters(codec="utf-8", exclude_characters="[]=\\")).filter(
    lambda text: all(text.split("."))
)
"""Any text with no ``[ ] = \\`` and no empty key between its dots."""


@given(TEXT)
def test_text_without_brackets_escapes_or_equals_reads_as_split_at_dots(text: str) -> None:
    assert list(read(text)) == text.split(".")


@given(st.lists(PLAIN, min_size=1, max_size=6))
def test_plain_keys_joined_by_dots_read_back_as_the_same_keys(keys: list[str]) -> None:
    assert list(read(".".join(keys))) == keys
