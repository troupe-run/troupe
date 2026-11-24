"""The runner's options: each rule, and the code agreeing with the published schema (spec:
claude-code-runner, "The runner's options are closed"; design D10)."""

from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from claude_harness import own_validator
from troupe_runner_claude_code.options import (
    PERMISSION_MODES,
    SETTING_SOURCES,
    WIDENING_MODES,
    Options,
    OptionsError,
    parse_options,
)

SCHEMA = own_validator("options.schema.json")


def _refusal(options: object) -> OptionsError:
    with pytest.raises(OptionsError) as caught:
        parse_options(options)
    return caught.value


def test_no_options_are_the_defaults() -> None:
    assert parse_options({}) == Options()


def test_every_option_together_is_parsed() -> None:
    parsed = parse_options(
        {
            "model": "claude-haiku-5-5",
            "maxBudgetUsd": 1,
            "permissionMode": "plan",
            "allowedTools": ["Bash(git status)", "Read"],
            "disallowedTools": ["WebFetch"],
            "settingSources": ["project"],
        }
    )
    assert parsed == Options(
        model="claude-haiku-5-5",
        max_budget_usd=1.0,
        permission_mode="plan",
        allowed_tools=("Bash(git status)", "Read"),
        disallowed_tools=("WebFetch",),
        setting_sources=("project",),
    )


def test_an_unknown_option_is_refused_naming_it() -> None:
    refusal = _refusal({"troupeConformanceUnknownOption": True})
    assert refusal.code == "claude-code.unknown-option"
    assert refusal.where == "options.troupeConformanceUnknownOption"
    assert "maxBudgetUsd" in refusal.fix


def test_options_that_arent_an_object_are_refused() -> None:
    refusal = _refusal(["model"])
    assert (refusal.code, refusal.where) == ("claude-code.invalid-options", "options")


@pytest.mark.parametrize(
    ("options", "where", "named"),
    [
        ({"model": ""}, "options.model", "model name"),
        ({"model": 5}, "options.model", "model name"),
        ({"model": "-p"}, "options.model", "model name"),
        ({"model": "haiku\n"}, "options.model", "model name"),
        ({"maxBudgetUsd": -1}, "options.maxBudgetUsd", "above 0"),
        ({"maxBudgetUsd": 0}, "options.maxBudgetUsd", "above 0"),
        ({"maxBudgetUsd": True}, "options.maxBudgetUsd", "above 0"),
        ({"maxBudgetUsd": "5"}, "options.maxBudgetUsd", "above 0"),
        ({"permissionMode": "yolo"}, "options.permissionMode", "dontAsk"),
        ({"allowedTools": "Read"}, "options.allowedTools", "JSON array"),
        ({"allowedTools": ["Read", "Read"]}, "options.allowedTools[1]", "once"),
        ({"allowedTools": [""]}, "options.allowedTools[0]", "Bash(git status)"),
        ({"disallowedTools": ["Bash\t"]}, "options.disallowedTools[0]", "Bash(git status)"),
        ({"settingSources": ["policy"]}, "options.settingSources[0]", "project"),
        ({"settingSources": ["user", "user"]}, "options.settingSources[1]", "once"),
    ],
)
def test_a_malformed_value_is_refused_naming_where_and_what_is_valid(
    options: dict[str, Any], where: str, named: str
) -> None:
    refusal = _refusal(options)
    assert refusal.code == "claude-code.invalid-options"
    assert refusal.where == where
    assert named in refusal.fix
    assert not SCHEMA.is_valid(options)


@pytest.mark.parametrize(
    "options",
    [
        {"model": "claude-opus-5-5[1m]"},
        {"maxBudgetUsd": 0.01},
        *({"permissionMode": mode} for mode in PERMISSION_MODES),
        {"allowedTools": []},
        {"settingSources": list(SETTING_SOURCES)},
        {"settingSources": []},
    ],
)
def test_a_valid_value_is_accepted_by_the_code_and_the_schema(options: dict[str, Any]) -> None:
    parse_options(options)
    assert SCHEMA.is_valid(options)


_JSON = st.recursive(
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(),
    lambda children: (
        st.lists(children, max_size=4) | st.dictionaries(st.text(max_size=8), children, max_size=4)
    ),
    max_leaves=10,
)
_CONTROL = st.sampled_from(["\x00", "\n", "\t", "\x1f", "\x7f"])
_TEXT = (
    st.text(max_size=12)
    | st.builds(lambda text: "-" + text, st.text(max_size=8))
    | st.builds(lambda a, c, b: a + c + b, st.text(max_size=6), _CONTROL, st.text(max_size=6))
    | st.sampled_from(["", "Read", "Bash(git *)", "claude-haiku-5-5", "a\n"])
)
_NUMBER = (
    st.floats(allow_nan=False, allow_infinity=False)
    | st.integers()
    | st.booleans()
    | st.sampled_from([0, 0.0, -0.0, 1e-300, 5])
)
_VALUES: dict[str, st.SearchStrategy[object]] = {
    "model": _TEXT | _JSON,
    "maxBudgetUsd": _NUMBER | _JSON,
    "permissionMode": st.sampled_from([*PERMISSION_MODES, "default", ""]) | _TEXT | _JSON,
    "allowedTools": st.lists(_TEXT, max_size=4)
    | st.lists(st.sampled_from(["Read", "Edit"]), max_size=3)
    | _JSON,
    "disallowedTools": st.lists(_TEXT, max_size=4) | _JSON,
    "settingSources": st.lists(st.sampled_from([*SETTING_SOURCES, "policy"]), max_size=4) | _JSON,
}


def _accepted(options: object) -> bool:
    try:
        parse_options(options)
    except OptionsError:
        return False
    return True


@pytest.mark.parametrize("key", sorted(_VALUES))
@given(data=st.data())
def test_the_code_and_the_published_schema_agree_on_each_options_values(
    key: str, data: st.DataObject
) -> None:
    options = {key: data.draw(_VALUES[key])}
    assert _accepted(options) == SCHEMA.is_valid(options)


@given(st.fixed_dictionaries({}, optional={**_VALUES, "speed": _JSON}) | _JSON)
def test_the_code_and_the_published_schema_accept_exactly_the_same_options(
    options: object,
) -> None:
    assert _accepted(options) == SCHEMA.is_valid(options)


# Requirement: Options can't widen the effects (spec: claude-code-runner; declared-effects D8)


@pytest.mark.parametrize("mode", WIDENING_MODES)
def test_a_mode_that_approves_without_a_rule_is_refused_by_the_code_and_the_schema(
    mode: str,
) -> None:
    with pytest.raises(OptionsError) as caught:
        parse_options({"permissionMode": mode})
    assert caught.value.code == "claude-code.widens-effects"
    assert caught.value.where == "options.permissionMode"
    assert "effects.write" in caught.value.fix
    assert "Unset options.permissionMode" in caught.value.fix
    assert not SCHEMA.is_valid({"permissionMode": mode})


@pytest.mark.parametrize(
    "rule", ["Edit", "Edit(src/**)", "Write", "NotebookEdit(x)", "MultiEdit", "mcp__troupe__Delete"]
)
def test_an_allow_rule_for_an_editing_tool_is_refused_naming_it(rule: str) -> None:
    with pytest.raises(OptionsError) as caught:
        parse_options({"allowedTools": ["Read", rule]})
    assert caught.value.code == "claude-code.widens-effects"
    assert caught.value.where == "options.allowedTools[1]"
    assert rule in caught.value.problem
    assert not SCHEMA.is_valid({"allowedTools": ["Read", rule]})


@pytest.mark.parametrize("rule", ["Edit(docs/**)", "Write", "mcp__troupe__Move"])
def test_a_deny_rule_for_an_editing_tool_is_accepted(rule: str) -> None:
    assert parse_options({"disallowedTools": [rule]}).disallowed_tools == (rule,)
    assert SCHEMA.is_valid({"disallowedTools": [rule]})
