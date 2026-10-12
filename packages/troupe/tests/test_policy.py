"""Policy is read through one seam, with its source (spec: policy; design D6)."""

import pytest

from troupe.core import defaults
from troupe.core.errors import TroupeError
from troupe.core.policy import PolicyFlag, env_name, read_policy

VARIABLE = "TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE"


def test_the_variable_is_the_prefix_and_the_settings_name_in_capitals() -> None:
    assert env_name("allow_unenforced_local_stage") == VARIABLE


@pytest.mark.parametrize("env", [{}, {VARIABLE: ""}], ids=["unset", "empty"])
def test_an_absent_value_is_the_default_from_the_default_source(env: dict[str, str]) -> None:
    assert defaults.ALLOW_UNENFORCED_LOCAL_STAGE is False
    assert read_policy(env).allow_unenforced_local_stage == PolicyFlag(
        "allow_unenforced_local_stage", False, "default"
    )


@pytest.mark.parametrize(("raw", "value"), [("true", True), ("false", False)])
def test_true_and_false_are_read_from_the_env_source(raw: str, value: bool) -> None:
    assert read_policy({VARIABLE: raw}).allow_unenforced_local_stage == PolicyFlag(
        "allow_unenforced_local_stage", value, "env"
    )


@pytest.mark.parametrize("raw", ["yes", "TRUE", " true", "1", "true ", "on"])
def test_any_other_value_is_refused_naming_the_variable_the_value_and_the_accepted_ones(
    raw: str,
) -> None:
    with pytest.raises(TroupeError) as caught:
        read_policy({VARIABLE: raw})
    error = caught.value
    assert error.code == "policy.invalid-value"
    assert VARIABLE in error.problem
    assert repr(raw) in error.problem
    assert error.details == {"variable": VARIABLE, "value": raw, "accepted": ["false", "true"]}
    assert "true" in error.fix
    assert "false" in error.fix
