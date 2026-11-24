"""The protocol guard's full-run check across pytest-xdist workers (spec: quality-check;
parallel-tests design D4).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_protocol_guard_workers.py."""

import pytest

import protocol_guard
from troupe.core import errors, notices


class _Gateway:
    def __init__(self, id: str) -> None:
        self.id = id


class _Node:
    """An xdist worker node as the controller sees it when the worker goes down."""

    def __init__(self, id: str, workeroutput: dict[str, object] | None) -> None:
        self.gateway = _Gateway(id)
        if workeroutput is not None:
            self.workeroutput = workeroutput


@pytest.fixture
def fresh(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty tally, so the merge is seen alone (and this session's own tally is untouched)."""
    monkeypatch.setattr(protocol_guard, "_seen", set())
    monkeypatch.setattr(protocol_guard, "_silent", [])


@pytest.mark.usefixtures("fresh")
def test_codes_split_across_workers_leave_nothing_unraised_though_no_worker_had_them_all() -> None:
    codes = sorted(set(errors.CODES) | set(notices.CODES))
    first, second = codes[::2], codes[1::2]

    protocol_guard.pytest_testnodedown(_Node("gw0", {protocol_guard.SEEN_KEY: first}), None)
    protocol_guard.pytest_testnodedown(_Node("gw1", {protocol_guard.SEEN_KEY: second}), None)

    assert protocol_guard.unraised() == []
    assert protocol_guard._silent == []


@pytest.mark.usefixtures("fresh")
def test_a_worker_that_went_down_without_reporting_its_codes_is_recorded_by_name() -> None:
    protocol_guard.pytest_testnodedown(_Node("gw0", {protocol_guard.SEEN_KEY: []}), None)
    protocol_guard.pytest_testnodedown(_Node("gw1", None), "worker crashed")
    protocol_guard.pytest_testnodedown(_Node("gw2", {"exitstatus": 0}), None)

    assert protocol_guard._silent == ["gw1", "gw2"]
