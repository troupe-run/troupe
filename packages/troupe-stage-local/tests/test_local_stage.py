"""The local stage refuses unless policy allows it (spec: stages; perform-status-logs design D5)."""

from pathlib import Path

import pytest

from troupe.core.errors import TroupeError
from troupe.core.events.lineage import Allowance, StageLineage
from troupe.core.policy import read_policy
from troupe_stage_local import LocalStage

VARIABLE = "TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE"


@pytest.mark.parametrize("env", [{}, {VARIABLE: "false"}], ids=["default", "set to false"])
def test_the_local_stage_refuses_naming_the_setting_and_how_to_set_it(
    env: dict[str, str],
) -> None:
    with pytest.raises(TroupeError) as caught:
        LocalStage().admit(read_policy(env))
    error = caught.value
    assert error.code == "stage.effects-unenforced"
    assert "allow_unenforced_local_stage" in error.problem
    assert f"{VARIABLE}=true" in error.fix
    assert error.details["variable"] == VARIABLE


def test_an_allowed_admission_records_unenforced_effects_and_the_setting_and_source() -> None:
    admission = LocalStage().admit(read_policy({VARIABLE: "true"}))
    assert admission == StageLineage(
        name="local",
        effects="unenforced",
        allowed_by=Allowance(setting="allow_unenforced_local_stage", source="env"),
    )
    assert admission.to_data() == {
        "name": "local",
        "effects": "unenforced",
        "allowedBy": {"setting": "allow_unenforced_local_stage", "source": "env"},
    }


def test_the_workspace_is_the_theatre_root(tmp_path: Path) -> None:
    assert LocalStage().workspace(tmp_path) == tmp_path
