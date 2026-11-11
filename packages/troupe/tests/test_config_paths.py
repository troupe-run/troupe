"""Config paths as people type and read them (spec: config, "A config path can put any key in
brackets", "A config path is shown in the form it is typed", "A malformed config path is refused";
config-path-dotted-keys design D2, D3, D6).

The first two properties pin what the reader accepted before brackets existed: they were written
against ``troupe.cli.values.split_path`` and passed there before the reader changed (task 1.1), so
the bracket reader can't quietly break a path that already worked.
"""

import json
import re
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from protocol_schemas import check_error
from troupe.core import config_paths as paths
from troupe.core.errors import TroupeError

PLAIN = st.text(st.characters(codec="utf-8", exclude_characters=".[]=\\"), min_size=1)
"""A key the old reader could read: non-empty, and holding none of ``. [ ] = \\``."""

TEXT = st.text(st.characters(codec="utf-8", exclude_characters="[]=\\")).filter(
    lambda text: all(text.split("."))
)
"""Any text with no ``[ ] = \\`` and no empty key between its dots."""

ANY_KEY = st.text(st.characters(codec="utf-8"), min_size=1)
"""Any non-empty key, whatever it holds: a model's name may hold any character."""


@given(TEXT)
def test_text_without_brackets_escapes_or_equals_reads_as_split_at_dots(text: str) -> None:
    assert list(paths.parse(text)) == text.split(".")


@given(st.lists(PLAIN, min_size=1, max_size=6))
def test_plain_keys_joined_by_dots_read_back_as_the_same_keys(keys: list[str]) -> None:
    assert list(paths.parse(".".join(keys))) == keys


@given(st.lists(PLAIN, min_size=1, max_size=6))
def test_plain_keys_are_shown_joined_by_dots_as_before(keys: list[str]) -> None:
    assert paths.shown(keys) == ".".join(keys)


@given(st.lists(ANY_KEY, min_size=1, max_size=6))
def test_any_shown_path_reads_back_as_the_same_keys(keys: list[str]) -> None:
    assert paths.parse(paths.shown(keys)) == tuple(keys)


@given(st.lists(ANY_KEY, min_size=1, max_size=6), st.text(st.characters(codec="utf-8")))
def test_a_shown_path_followed_by_equals_ends_at_that_equals(keys: list[str], value: str) -> None:
    shown = paths.shown(keys)
    assert paths.parse_prefix(f"{shown}={value}") == (tuple(keys), len(shown))


@given(st.text(st.characters(codec="utf-8"), max_size=30))
def test_any_text_reads_as_non_empty_keys_or_is_refused_as_a_malformed_path(text: str) -> None:
    refused: TroupeError | None = None
    try:
        keys = paths.parse(text)
    except TroupeError as error:
        refused = error
    if refused is None:
        assert keys
        assert all(keys)
    else:
        assert refused.code == "config.path-malformed"
        offset = refused.details["offset"]
        assert 0 <= offset <= len(text)
        # Only what was read, up to and including where reading failed, or the [ of a bracket it
        # failed inside (design D6).
        shown = refused.details["text"]
        assert text.startswith(shown)
        assert shown == text[: offset + 1] or (shown.endswith("[") and len(shown) <= offset + 1)


# What the spec's examples read as, and how keys are shown.


@pytest.mark.parametrize(
    ("text", "keys"),
    [
        (
            "runtimes.openai.prices[gpt-4.1].input",
            ("runtimes", "openai", "prices", "gpt-4.1", "input"),
        ),
        ("actors.tester.runner", ("actors", "tester", "runner")),
        ("actors[tester].runner", ("actors", "tester", "runner")),
        ("[actors][tester][runner]", ("actors", "tester", "runner")),
        ("a[x\\]y\\\\z]", ("a", "x]y\\z")),
        ("runtimes.ollama.prices.llama3:3b", ("runtimes", "ollama", "prices", "llama3:3b")),
        ("a[k=v].b", ("a", "k=v", "b")),
        ("a[b.c[d]", ("a", "b.c[d")),
    ],
)
def test_a_path_reads_as_its_keys(text: str, keys: tuple[str, ...]) -> None:
    assert paths.parse(text) == keys


@pytest.mark.parametrize(
    ("keys", "text"),
    [
        (
            ("runtimes", "openai", "prices", "gpt-4.1", "input"),
            "runtimes.openai.prices[gpt-4.1].input",
        ),
        (("a", "x]y\\z"), "a[x\\]y\\\\z]"),
        (("a", "k=v"), "a[k=v]"),
        (("a", "[b"), "a[[b]"),
        (("llama3:3b",), "llama3:3b"),
        (("a", ""), "a[]"),
    ],
)
def test_a_key_that_needs_brackets_is_shown_in_them(keys: tuple[str, ...], text: str) -> None:
    assert paths.shown(keys) == text


def test_set_text_with_no_equals_outside_brackets_ends_at_its_end() -> None:
    assert paths.parse_prefix("a[k=v]") == (("a", "k=v"), 6)


# Each refusal in design D2.


@pytest.mark.parametrize(
    ("text", "offset", "rule"),
    [
        ("actors..runner", 7, paths.EMPTY),
        ("actors.", 7, paths.EMPTY),
        (".actors", 0, paths.EMPTY),
        ("a[]", 1, paths.EMPTY),
        ("", 0, paths.EMPTY),
        ("runtimes.openai.prices[gpt-4.1", 22, paths.UNCLOSED),
        ("a[b\\", 3, paths.ESCAPES_NOTHING),
        ("a[b\\.c]", 3, paths.UNKNOWN_ESCAPE),
        ("runtimes.openai.prices.gpt-4\\.1.input", 28, paths.BACKSLASH_OUTSIDE),
        ("a[b]c", 4, paths.AFTER_BRACKET),
        ("a.[b]", 1, paths.DOT_BEFORE_BRACKET),
        ("a]b", 1, paths.STRAY_CLOSE),
        ("a[b]]", 4, paths.STRAY_CLOSE),
        ("a=b", 1, paths.EQUALS_OUTSIDE),
        ("a.=b", 2, paths.EQUALS_OUTSIDE),
    ],
)
def test_a_malformed_path_is_refused_naming_the_text_read_where_and_the_rule(
    text: str, offset: int, rule: str
) -> None:
    with pytest.raises(TroupeError) as caught:
        paths.parse(text)
    error = caught.value
    inside = rule in (paths.ESCAPES_NOTHING, paths.UNKNOWN_ESCAPE)  # shown up to the bracket's [
    read = text[: text.index("[") + 1] if inside else text[: offset + 1]
    assert error.code == "config.path-malformed"
    assert error.details == {"text": read, "offset": offset, "rule": rule}
    assert f'"{read}"' in error.problem
    assert rule in error.problem
    assert f"at character {offset + 1}" in error.problem
    check_error(error.to_data())


@pytest.mark.parametrize("text", ["a.=1", "=1", "a[b].=1"])
def test_an_empty_key_before_a_set_equals_is_refused_as_empty(text: str) -> None:
    with pytest.raises(TroupeError) as caught:
        paths.parse_prefix(text)
    assert caught.value.details["rule"] == paths.EMPTY


def test_a_backslash_outside_brackets_is_fixed_by_putting_the_key_in_brackets() -> None:
    with pytest.raises(TroupeError) as caught:
        paths.parse("runtimes.openai.prices.gpt-4\\.1.input")
    assert "in brackets, such as [gpt-4.1]" in caught.value.fix


def test_a_dot_before_a_bracket_is_fixed_by_dropping_the_dot() -> None:
    with pytest.raises(TroupeError) as caught:
        paths.parse("a.[b]")
    assert "'a[b]'" in caught.value.fix


CANARY = "q7ZxW9pL4vR2canary"


@pytest.mark.parametrize(
    "text",
    [
        f"a]b={CANARY}",
        f"runtimes.box.endpoint.=https://user:{CANARY}@example.com/v1",
        f"a.[b]=https://user:{CANARY}@example.com/v1",
        f"a.[b]c={CANARY}",
        f"a[b]c={CANARY}",
        f"a\\b={CANARY}",
        f"a[b=https://user:{CANARY}@h\\x",
        f"a[b=https://user:{CANARY}@h\\",
        f"a.[b=https://user:{CANARY}@h\\q]",
    ],
)
def test_a_malformed_path_in_config_set_shows_none_of_the_value(text: str) -> None:
    with pytest.raises(TroupeError) as caught:
        paths.parse_prefix(text)
    error = caught.value
    assert error.code == "config.path-malformed"
    assert CANARY not in json.dumps([error.problem, error.fix, error.details])


@pytest.mark.parametrize("text", [f"runtimes.box.endpoint=https://user:{CANARY}@example.com/v1"])
def test_a_path_given_a_value_where_none_is_taken_shows_none_of_it(text: str) -> None:
    with pytest.raises(TroupeError) as caught:
        paths.parse(text)
    error = caught.value
    assert error.details["rule"] == paths.EQUALS_OUTSIDE
    assert error.details["text"] == "runtimes.box.endpoint="
    assert CANARY not in json.dumps([error.problem, error.fix, error.details])


def test_a_dot_before_an_unclosed_bracket_is_fixed_without_the_rest() -> None:
    with pytest.raises(TroupeError) as caught:
        paths.parse_prefix(f"a.[b={CANARY}")
    assert caught.value.details["rule"] == paths.DOT_BEFORE_BRACKET
    assert "such as a[b]" in caught.value.fix
    assert CANARY not in caught.value.fix


# No message builds a config path by hand (review of #324: runtimes.py's fix did, and a key with a
# dot came out split). Every one goes through shown.

SOURCE = Path(__file__).resolve().parents[1] / "src" / "troupe"
HAND_BUILT = re.compile(
    r"""f"[^"]*\b(?:actors|runtimes)\.\{|f'[^']*\b(?:actors|runtimes)\.\{|\{RUNTIMES\}\."""
)


def test_no_source_builds_a_config_path_with_a_name_in_an_f_string() -> None:
    found = [
        f"{path.relative_to(SOURCE)}:{number}: {line.strip()}"
        for path in sorted(SOURCE.rglob("*.py"))
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if HAND_BUILT.search(line)
    ]
    assert found == []
