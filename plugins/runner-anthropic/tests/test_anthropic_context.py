"""The context guard's three judgements (spec: anthropic-runner, "A context-length refusal ends the
run with context-length", "A reply from a conversation the engine shrank isn't acted on", "A run
stops before the context window the person named"; design D8).

These check context.py's table and arithmetic. That the loop acts on them (no turn, no tool call,
the result's reason) is the loop tests' to show."""

from itertools import pairwise

import pytest
from hypothesis import given
from hypothesis import strategies as st

from troupe_runner_anthropic.context import (
    SIGNALS,
    Window,
    against_window,
    shrank,
    signal_of,
)

CLAUDE = "prompt is too long: 210000 tokens > 200000 maximum"
"""Claude's refusal, as the spec's scenario "Claude's refusal" gives it."""
LM_STUDIO = (
    "The number of tokens to keep from the initial prompt is greater than the context length. Try "
    "to load the model with a larger context length, or provide a shorter input"
)
"""LM Studio's, as fixtures/lm-studio-context-refused holds it."""
LLAMA_CPP = "the request exceeds the available context size, try increasing it"
"""llama.cpp's, as its server documentation gives it (not yet probed, as SIGNALS says)."""

ENGINES = {signal.engine: signal for signal in SIGNALS}


# Requirement: A context-length refusal ends the run with context-length (the one table)


def test_the_table_holds_claudes_and_each_local_engines_signal() -> None:
    assert set(ENGINES) == {"Claude's API", "LM Studio", "llama.cpp"}
    for signal in SIGNALS:
        assert signal.says
        assert signal.pinned_by


@pytest.mark.parametrize(
    ("status", "error_type", "message", "engine"),
    [
        (400, "invalid_request_error", CLAUDE, "Claude's API"),
        (400, "invalid_request_error", CLAUDE.upper(), "Claude's API"),
        (200, "api_error", LM_STUDIO, "LM Studio"),
        (500, "api_error", LM_STUDIO, "LM Studio"),
        (400, "exceed_context_size_error", LLAMA_CPP, "llama.cpp"),
    ],
    ids=[
        "claude",
        "claude in capitals",
        "lm studio in a stream",
        "lm studio as a 500",
        "llama.cpp",
    ],
)
def test_each_engines_refusal_matches_its_own_entry(
    status: int, error_type: str, message: str, engine: str
) -> None:
    assert signal_of(status, error_type, message) == ENGINES[engine]


@pytest.mark.parametrize("status", [200, 400, 413, 500, 503])
def test_an_entry_with_no_status_matches_any_status(status: int) -> None:
    assert ENGINES["LM Studio"].status is None
    assert signal_of(status, "api_error", LM_STUDIO) == ENGINES["LM Studio"]


@pytest.mark.parametrize(
    ("status", "error_type", "message"),
    [
        (400, "not_found_error", CLAUDE),
        (400, None, CLAUDE),
        (413, "invalid_request_error", CLAUDE),
        (200, "overloaded_error", LM_STUDIO),
        (200, None, LM_STUDIO),
        (400, "invalid_request_error", LLAMA_CPP),
    ],
    ids=[
        "claude's words, another type",
        "claude's words, no type",
        "claude's words, another status",
        "lm studio's words, another type",
        "lm studio's words, no type",
        "llama.cpp's words, claude's type",
    ],
)
def test_an_entrys_words_with_another_status_or_type_match_nothing(
    status: int, error_type: str | None, message: str
) -> None:
    assert signal_of(status, error_type, message) is None


@pytest.mark.parametrize(
    ("status", "error_type", "message"),
    [
        (500, "api_error", "Internal server error"),
        (500, "api_error", None),
        (529, "overloaded_error", "Overloaded"),
        (400, "invalid_request_error", "max_tokens: must be positive"),
        (400, "invalid_request_error", None),
    ],
)
def test_a_failure_with_another_message_matches_nothing(
    status: int, error_type: str, message: str | None
) -> None:
    assert signal_of(status, error_type, message) is None


# Requirement: A reply from a conversation the engine shrank isn't acted on (guard 2)


def test_a_prompt_smaller_than_the_previous_requests_shrank() -> None:
    """Scenario "An engine that cuts the middle": 5,900 then 4,058."""
    assert shrank(5900, 4058) is True


@pytest.mark.parametrize(
    ("previous", "current"),
    [(5900, 5900), (5900, 6200), (None, 4058), (5900, None), (None, None), (0, 0)],
)
def test_a_prompt_as_large_or_unknown_didnt_shrink(
    previous: int | None, current: int | None
) -> None:
    assert shrank(previous, current) is False


@given(st.lists(st.integers(min_value=0, max_value=10**9), max_size=30).map(sorted))
def test_a_conversation_that_never_gets_smaller_never_shrinks(sizes: list[int]) -> None:
    """Scenario "A conversation that grows", for any non-decreasing sizes."""
    assert not any(shrank(previous, current) for previous, current in pairwise(sizes))


@given(
    st.lists(st.integers(min_value=0, max_value=10**9), min_size=2, max_size=30),
)
def test_shrank_is_true_exactly_where_a_size_drops(sizes: list[int]) -> None:
    for previous, current in pairwise(sizes):
        assert shrank(previous, current) is (current < previous)


# Requirement: A run stops before the context window the person named (guard 3)


def test_a_prompt_and_output_reaching_the_window_is_full_but_not_cut() -> None:
    """Scenario "The window is reached": 7,900 prompt and 300 output tokens against 8,192."""
    assert against_window(8192, 7900, 300) == Window(cut=False, full=True)


@pytest.mark.parametrize(
    ("prompt", "output", "expected"),
    [
        (8192, 0, Window(cut=True, full=True)),
        (9000, 10, Window(cut=True, full=True)),
        (8191, 1, Window(cut=False, full=True)),
        (8191, 0, Window(cut=False, full=False)),
        (8191, None, Window(cut=False, full=False)),
        (8000, 191, Window(cut=False, full=False)),
    ],
)
def test_the_window_is_reached_at_equality(
    prompt: int, output: int | None, expected: Window
) -> None:
    assert against_window(8192, prompt, output) == expected


@pytest.mark.parametrize(("window", "prompt"), [(None, 10**9), (8192, None), (None, None)])
def test_no_window_or_no_prompt_size_is_neither_cut_nor_full(
    window: int | None, prompt: int | None
) -> None:
    """Scenario "No window named"."""
    assert against_window(window, prompt, 10**9) == Window(cut=False, full=False)
