"""Helpers of the conversation's tool loop: the tool limits follow the context window and never pass
the SDK's defaults, encode writes compact UTF-8, and fit_output keeps a tool's output within a
budget smaller than its note (spec: ollama-runner; local-model-runner design D15).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_ollama_conversation.py."""

from ollama_conversation_shared import WINDOW
from troupe_plugin_sdk.defaults import (
    GLOB_MAX_PATHS,
    GREP_MAX_MATCHES,
    READ_MAX_BYTES,
)
from troupe_runner_ollama.conversation import (
    encode,
    fit_output,
    tool_budget,
    tool_limits,
)
from troupe_runner_ollama.defaults import (
    READ_NOTE_BYTES,
)

# Requirement: One tool result fits the context window


def test_the_tool_limits_follow_the_window_and_never_pass_the_sdks_defaults() -> None:
    default = tool_limits(WINDOW)
    assert default.read_max_bytes == tool_budget(WINDOW) - READ_NOTE_BYTES
    assert default.read_max_bytes < READ_MAX_BYTES
    small, large = tool_limits(8192), tool_limits(32768)
    assert small.read_max_bytes < default.read_max_bytes < large.read_max_bytes
    assert small.grep_max_matches < large.grep_max_matches
    huge = tool_limits(10_000_000)
    assert huge.read_max_bytes == READ_MAX_BYTES
    assert huge.glob_max_paths == GLOB_MAX_PATHS
    assert huge.grep_max_matches == GREP_MAX_MATCHES


def test_encode_is_compact_utf8() -> None:
    assert encode({"a": "é", "b": [1, 2]}) == '{"a":"é","b":[1,2]}'.encode()


def test_fit_output_stays_within_a_budget_smaller_than_its_note() -> None:
    assert len(fit_output("x" * 500, 40).encode("utf-8")) <= 40
    assert fit_output("short", 40) == "short"
