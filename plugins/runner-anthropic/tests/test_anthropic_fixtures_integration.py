"""Each fixture replays through the fake endpoint and the real runner to the events it expects, and
the runner writes no part of the credential (spec: anthropic-runner, "Fixtures pair service
output with protocol events"; design D12, D14).

Its tests that stay in their own process are in unit/test_anthropic_fixtures.py."""

from pathlib import Path

import pytest

from anthropic_fixture_replay import ECHO, NAMES, load, replay
from anthropic_harness import CANARY


@pytest.mark.parametrize("name", NAMES)
def test_each_fixture_replays_to_its_expected_events_and_writes_no_part_of_the_credential(
    name: str, tmp_path: Path
) -> None:
    expected = load(name, "expected.json")
    replayed = replay(name, tmp_path)
    assert replayed.requests == expected["requests"]
    assert replayed.events == expected["events"]
    written = replayed.written
    for secret in (CANARY, CANARY[:-1], CANARY[1:], ECHO):
        assert secret.encode() not in written
