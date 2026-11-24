"""Stages are a port, found by name (spec: stages; perform-status-logs design D5)."""

import pytest

from troupe.core import defaults
from troupe.core.errors import TroupeError
from troupe.core.stages import load_stage


def test_an_unknown_stage_fails_naming_the_installed_stages() -> None:
    with pytest.raises(TroupeError) as caught:
        load_stage("docker")
    assert caught.value.code == "stage.unknown"
    assert "'docker'" in caught.value.problem
    assert "local" in caught.value.problem
    assert caught.value.details == {"stage": "docker", "installed": ["local"]}


def test_the_default_stage_is_installed_and_found_by_name() -> None:
    assert load_stage(defaults.STAGE).name == defaults.STAGE == "local"
