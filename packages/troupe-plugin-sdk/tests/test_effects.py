"""Declared effects and their path patterns (spec: runner-tools, "Effects are declared as path
patterns"; runner-sdk design D7)."""

import fnmatch

import pytest
from hypothesis import given
from hypothesis import strategies as st

from troupe_plugin_sdk.effects import EFFECTS, READ_ONLY, Effects, PathPattern, PatternError

MATCHES = [
    ("src/**", "src/a.py", True),
    ("src/**", "src/pkg/b.py", True),
    ("src/**", "tests/a.py", False),
    ("src/**", "src", False),
    ("**/*.py", "a.py", True),
    ("**/*.py", "x/y/a.py", True),
    ("**/*.py", "x/y/a.pyc", False),
    ("*.py", "x/a.py", False),
    ("out/*.txt", "out/a.txt", True),
    ("out/*.txt", "out/sub/a.txt", False),
    ("out/?.txt", "out/a.txt", True),
    ("out/?.txt", "out/ab.txt", False),
    ("a/**/b", "a/b", True),
    ("a/**/b", "a/x/y/b", True),
    ("**", "anything/at/all", True),
    ("out/hello.txt", "out/hello.txt", True),
    ("out/hello.txt", "out/Hello.txt", False),
    ("docs/[draft].md", "docs/[draft].md", True),
    ("docs/[draft].md", "docs/d.md", False),
]


@pytest.mark.parametrize(("pattern", "path", "expected"), MATCHES)
def test_a_pattern_matches_exactly_the_paths_its_language_describes(
    pattern: str, path: str, expected: bool
) -> None:
    assert PathPattern(pattern).matches(path) is expected


MALFORMED = [
    ("/tmp/**", "absolute"),  # noqa: S108 - a pattern, never a file opened
    ("", "empty"),
    ("src/../secret", "'..'"),
    ("src\\a.py", "'\\'"),
    ("C:/x", "':'"),
    ("src//a.py", "empty part"),
    ("src/", "empty part"),
    ("./src", "empty part"),
    ("src/a**", "'**' inside a part"),
    ("***", "'**' inside a part"),
]


@pytest.mark.parametrize(("pattern", "problem"), MALFORMED)
@pytest.mark.parametrize("effect", ["write", "delete", "move"])
def test_a_malformed_pattern_is_refused_naming_its_effect_and_the_pattern(
    effect: str, pattern: str, problem: str
) -> None:
    with pytest.raises(PatternError) as refused:
        Effects(**{effect: (pattern,)})
    message = str(refused.value)
    assert message.startswith(f"{effect}: {pattern!r}")
    assert problem in message


def test_the_specs_malformed_delete_pattern_says_patterns_are_workspace_relative() -> None:
    with pytest.raises(
        PatternError, match=r"delete: '/tmp/\*\*' is absolute; patterns are relative"
    ):
        Effects(delete=("/tmp/**",))  # noqa: S108 - a pattern, never a file opened


def test_one_string_instead_of_a_list_is_refused() -> None:
    with pytest.raises(PatternError, match="write: a list of patterns"):
        Effects(write="src/**")  # type: ignore[arg-type]


def test_with_nothing_declared_no_effect_is_allowed_anywhere() -> None:
    for effect in EFFECTS:
        assert not READ_ONLY.allows(effect, "a.txt")


def test_each_effect_is_allowed_only_by_its_own_patterns() -> None:
    effects = Effects(write=("out/**",), delete=("tmp/**",), move=("drafts/**",))
    assert effects.allows("write", "out/a")
    assert not effects.allows("delete", "out/a")
    assert not effects.allows("move", "out/a")
    assert effects.allows("delete", "tmp/a")
    assert not effects.allows("write", "tmp/a")
    assert effects.allows("move", "drafts/a")
    assert effects.declared("write") == ("out/**",)


def _reference(pattern: list[str], path: list[str]) -> bool:
    """An independent matcher, part by part: ``**`` takes zero or more whole parts, except at the
    end, where it takes at least one; any other part matches one part with fnmatchcase (whose ``*``
    and ``?`` never meet a ``/`` here, since the parts have none)."""
    if not pattern:
        return not path
    head, rest = pattern[0], pattern[1:]
    if head == "**":
        if not rest:
            return len(path) >= 1
        return any(_reference(rest, path[i:]) for i in range(len(path) + 1))
    if not path:
        return False
    literal = head.replace("[", "[[]")
    return fnmatch.fnmatchcase(path[0], literal) and _reference(rest, path[1:])


PATTERN_PART = st.sampled_from(["**", "*", "?", "a", "b", "*.py", "a?", "x*y", "[c]"])
PATH_PART = st.sampled_from(["a", "b", "a.py", "ab", "xy", "xzy", "[c]", "c"])


@given(st.lists(PATTERN_PART, min_size=1, max_size=5), st.lists(PATH_PART, min_size=1, max_size=5))
def test_the_matcher_agrees_with_a_part_by_part_matcher(
    pattern: list[str], path: list[str]
) -> None:
    assert PathPattern("/".join(pattern)).matches("/".join(path)) is _reference(pattern, path)
