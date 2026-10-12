"""troupe-identity-local is found by name through its entry point group (event-store design D1)."""

import importlib.metadata

import pytest

REGISTERED = [
    ("troupe.identity", "env", "troupe_identity_local:EnvSource"),
    ("troupe.identity", "vcs", "troupe_identity_local:VcsSource"),
    ("troupe.identity", "os-login", "troupe_identity_local:OsLoginSource"),
]


@pytest.mark.parametrize(("group", "name", "target"), REGISTERED)
def test_the_package_is_registered_under_its_name_in_its_entry_point_group(
    group: str, name: str, target: str
) -> None:
    found = {ep.name: ep.value for ep in importlib.metadata.entry_points(group=group)}
    assert found.get(name) == target
