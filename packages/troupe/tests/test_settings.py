"""Settings are read through one seam, with their source (spec: settings; mark-config-resolved
design D1, D2)."""

import json
from typing import Any

import pytest

from client_schemas import CLIENT_SCHEMAS, is_valid
from troupe.core import defaults
from troupe.core.errors import TroupeError
from troupe.core.settings import Marking, SettingFlag, env_name, marking, read_settings

VARIABLE = "TROUPE_SETTING_MARK_MERGES_RESOLVED"
POLICY = "TROUPE_POLICY_ALLOW_MARK_MERGES_RESOLVED"


def test_the_variable_is_the_prefix_and_the_settings_name_in_capitals() -> None:
    assert env_name("mark_merges_resolved") == VARIABLE


# Requirement: Settings are read through one seam


@pytest.mark.parametrize("env", [{}, {VARIABLE: ""}], ids=["unset", "empty"])
def test_an_absent_value_is_the_default_false_from_the_default_source(
    env: dict[str, str],
) -> None:
    assert defaults.MARK_MERGES_RESOLVED is False
    assert read_settings(env).mark_merges_resolved == SettingFlag(
        "mark_merges_resolved", False, "default"
    )


# Requirement: The environment is a settings source


@pytest.mark.parametrize(("raw", "value"), [("true", True), ("false", False)])
def test_true_and_false_are_read_from_the_env_source(raw: str, value: bool) -> None:
    assert read_settings({VARIABLE: raw}).mark_merges_resolved == SettingFlag(
        "mark_merges_resolved", value, "env"
    )


def _property_names(schema: Any) -> set[str]:  # noqa: ANN401 - any JSON value
    """Every property name a schema declares, at any depth."""
    names: set[str] = set()
    if isinstance(schema, dict):
        names |= set(schema.get("properties", {}))
        for value in schema.values():
            names |= _property_names(value)
    elif isinstance(schema, list):
        for value in schema:
            names |= _property_names(value)
    return names


def test_no_request_schema_declares_a_field_named_for_a_setting() -> None:
    requests = sorted(CLIENT_SCHEMAS.glob("*-request.schema.json"))
    assert requests
    for path in requests:
        names = _property_names(json.loads(path.read_text(encoding="utf-8")))
        assert not names & {"mark_merges_resolved", "markMergesResolved"}, path.name


def test_a_flush_request_carrying_the_setting_is_invalid() -> None:
    assert is_valid({"rehearse": False}, "flush-request.schema.json")
    assert not is_valid(
        {"rehearse": False, "markMergesResolved": True}, "flush-request.schema.json"
    )


# Requirement: A malformed setting is an error


@pytest.mark.parametrize("raw", ["yes", "TRUE", " true", "1", "true ", "on"])
def test_any_other_value_is_refused_naming_the_variable_the_value_and_the_accepted_ones(
    raw: str,
) -> None:
    with pytest.raises(TroupeError) as caught:
        read_settings({VARIABLE: raw})
    error = caught.value
    assert error.code == "settings.invalid-value"
    assert VARIABLE in error.problem
    assert repr(raw) in error.problem
    assert error.details == {"variable": VARIABLE, "value": raw, "accepted": ["false", "true"]}
    assert "true" in error.fix
    assert "false" in error.fix


# Marking: the setting, bounded by policy (config-files, "Policy can forbid marking a file
# resolved"; design D2)


def test_with_the_setting_off_marking_is_off_because_of_the_setting_and_policy_isnt_read() -> None:
    # A malformed policy value would fail if it were read.
    assert marking({POLICY: "nope"}) == Marking(False, "setting")
    assert marking({VARIABLE: "false", POLICY: "nope"}) == Marking(False, "setting")


def test_with_the_setting_on_and_policy_unset_marking_is_on() -> None:
    assert defaults.ALLOW_MARK_MERGES_RESOLVED is True
    assert marking({VARIABLE: "true"}) == Marking(True)


def test_with_the_setting_on_and_policy_false_marking_is_off_because_of_policy() -> None:
    assert marking({VARIABLE: "true", POLICY: "false"}) == Marking(False, "policy")


def test_with_the_setting_on_a_malformed_policy_value_is_refused() -> None:
    with pytest.raises(TroupeError) as caught:
        marking({VARIABLE: "true", POLICY: "nope"})
    assert caught.value.code == "policy.invalid-value"


def test_a_malformed_setting_is_refused_whatever_policy_says() -> None:
    with pytest.raises(TroupeError) as caught:
        marking({VARIABLE: "yes", POLICY: "true"})
    assert caught.value.code == "settings.invalid-value"
