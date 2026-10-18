"""troupe-stage-local is found by name through its entry point group (perform-status-logs design
D1)."""

import importlib.metadata

import pytest

from troupe.core.stages import load_stage
from troupe_stage_local import LocalStage

REGISTERED = [
    ("troupe.stages", "local", "troupe_stage_local:LocalStage"),
]


@pytest.mark.parametrize(("group", "name", "target"), REGISTERED)
def test_the_package_is_registered_under_its_name_in_its_entry_point_group(
    group: str, name: str, target: str
) -> None:
    found = {ep.name: ep.value for ep in importlib.metadata.entry_points(group=group)}
    assert found.get(name) == target


def test_the_entry_point_loads_the_local_stage() -> None:
    assert isinstance(load_stage("local"), LocalStage)
