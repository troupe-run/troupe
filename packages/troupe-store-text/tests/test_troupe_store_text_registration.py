"""troupe-store-text is found by name through its entry point group, and implements the port
(event-store design D1)."""

import importlib.metadata
from pathlib import Path

import pytest

from troupe.core.events import EventRecorder
from troupe.core.vcs import load_vcs
from troupe_store_text import open_store

REGISTERED = [
    ("troupe.store", "text", "troupe_store_text:open_store"),
]


@pytest.mark.parametrize(("group", "name", "target"), REGISTERED)
def test_the_package_is_registered_under_its_name_in_its_entry_point_group(
    group: str, name: str, target: str
) -> None:
    found = {ep.name: ep.value for ep in importlib.metadata.entry_points(group=group)}
    assert found.get(name) == target


def test_the_opened_store_is_an_event_recorder_as_the_port_defines_it(tmp_path: Path) -> None:
    # mypy checks this assignment structurally, against every method of the port's protocol,
    # listen and unlisten included; the assertions check the same at run time.
    store: EventRecorder = open_store(tmp_path, load_vcs("files", tmp_path))
    assert callable(store.listen)
    assert callable(store.unlisten)
