"""Tests for environment policies (spec: platform)."""

import sys

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from troupe.core import defaults
from troupe.platform.errors import EnvironmentPolicyError
from troupe.platform.processes import MINIMUM_ENVIRONMENT, EnvironmentPolicy, build_environment

WINDOWS = sys.platform == "win32"
MINIMUM = {name: "C:\\Windows" for name in MINIMUM_ENVIRONMENT}


def _without_minimum(environment: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in environment.items() if k not in MINIMUM_ENVIRONMENT}


# Requirement: A child's environment is explicit and built from a declared policy


def test_only_the_names_and_prefixes_a_policy_selects_pass() -> None:
    policy = EnvironmentPolicy(names=frozenset({"A"}), prefixes=("GIT_",))
    source = {**MINIMUM, "A": "1", "GIT_X": "2", "B": "3"}
    environment = build_environment(policy, source=source)
    assert _without_minimum(environment) == {"A": "1", "GIT_X": "2"}
    assert {k: environment[k] for k in MINIMUM_ENVIRONMENT} == MINIMUM


def test_a_never_passed_name_is_dropped_from_the_source_and_refused_when_given_explicitly() -> None:
    policy = EnvironmentPolicy(prefixes=("GIT_",), never=frozenset({"GIT_DIR"}))
    environment = build_environment(policy, source={"GIT_DIR": "/repo/.git", "GIT_X": "1"})
    assert "GIT_DIR" not in environment
    with pytest.raises(EnvironmentPolicyError) as caught:
        build_environment(policy, source={}, explicit={"GIT_DIR": "/elsewhere"})
    assert caught.value.name == "GIT_DIR"


def test_a_never_passed_prefix_wins_over_a_selected_prefix() -> None:
    policy = EnvironmentPolicy(prefixes=("GIT_",), never_prefixes=("GIT_INDEX",))
    environment = build_environment(policy, source={"GIT_INDEX_FILE": "x", "GIT_X": "1"})
    assert _without_minimum(environment) == {"GIT_X": "1"}


def test_names_match_case_insensitively_on_windows_only() -> None:
    policy = EnvironmentPolicy(names=frozenset({"Path"}))
    environment = _without_minimum(build_environment(policy, source={"PATH": "/bin"}))
    if WINDOWS:
        assert environment == {"PATH": "/bin"}
    else:
        assert environment == {}


def test_explicit_values_are_added_on_top_of_the_selection() -> None:
    policy = EnvironmentPolicy(names=frozenset({"A"}))
    environment = build_environment(policy, source={"A": "1"}, explicit={"A": "2", "B": "3"})
    assert _without_minimum(environment) == {"A": "2", "B": "3"}


def test_the_runner_policy_selects_nothing_from_the_parent() -> None:
    environment = build_environment(
        defaults.RUNNER_ENVIRONMENT,
        source={**MINIMUM, "HOME": "/home/x", "ANTHROPIC_API_KEY": "secret"},
        explicit={"TROUPE_RUN": "1"},
    )
    assert _without_minimum(environment) == {"TROUPE_RUN": "1"}


NAMES = st.sampled_from(["A", "B", "GIT_DIR", "GIT_X", "GIT_INDEX_FILE", "HOME", "Path", "PATH"])


@settings(max_examples=200, deadline=None)
@given(
    names=st.frozensets(NAMES),
    prefixes=st.lists(st.sampled_from(["GIT_", "A", "H", ""]), max_size=2),
    never=st.frozensets(NAMES, min_size=1),
    never_prefixes=st.lists(st.sampled_from(["GIT_I", "B"]), max_size=2),
    source=st.dictionaries(NAMES, st.text(max_size=5)),
    explicit=st.dictionaries(NAMES, st.text(max_size=5)),
)
def test_a_built_environment_never_holds_a_never_passed_name(
    names: frozenset[str],
    prefixes: list[str],
    never: frozenset[str],
    never_prefixes: list[str],
    source: dict[str, str],
    explicit: dict[str, str],
) -> None:
    policy = EnvironmentPolicy(names, tuple(prefixes), never, tuple(never_prefixes))
    refused = [name for name in explicit if policy.forbids(name)]
    if refused:
        with pytest.raises(EnvironmentPolicyError):
            build_environment(policy, source=source, explicit=explicit)
        return
    environment = build_environment(policy, source=source, explicit=explicit)
    assert not any(policy.forbids(name) for name in _without_minimum(environment))


# Requirement: Environment policies can be narrowed but never widened


def test_narrowing_keeps_only_the_names_asked_for() -> None:
    policy = EnvironmentPolicy(names=frozenset({"A", "B"}))
    narrowed = policy.narrow(names={"A"})
    assert narrowed.names == frozenset({"A"})
    assert _without_minimum(build_environment(narrowed, source={"A": "1", "B": "2"})) == {"A": "1"}


def test_narrowing_can_add_never_passed_names_and_prefixes() -> None:
    policy = EnvironmentPolicy(prefixes=("GIT_",))
    narrowed = policy.narrow(never={"GIT_DIR"}, never_prefixes=("GIT_INDEX",))
    assert narrowed.forbids("GIT_DIR")
    assert narrowed.forbids("GIT_INDEX_FILE")
    assert narrowed.selects("GIT_X")


def test_narrowing_to_a_longer_prefix_of_a_selected_prefix_is_allowed() -> None:
    narrowed = EnvironmentPolicy(prefixes=("GIT_",)).narrow(prefixes=("GIT_CONFIG",))
    assert narrowed.selects("GIT_CONFIG_GLOBAL")
    assert not narrowed.selects("GIT_X")


def test_narrowing_cannot_select_a_name_the_policy_does_not_select() -> None:
    with pytest.raises(EnvironmentPolicyError) as caught:
        EnvironmentPolicy(names=frozenset({"A"})).narrow(names={"A", "SECRET"})
    assert caught.value.name == "SECRET"


def test_narrowing_cannot_select_a_wider_prefix() -> None:
    with pytest.raises(EnvironmentPolicyError) as caught:
        EnvironmentPolicy(prefixes=("GIT_CONFIG",)).narrow(prefixes=("GIT_",))
    assert caught.value.name == "GIT_"
