"""The capture tool refuses an endpoint that isn't on this machine, and the replay starts each
fixture with the files its capture made (local-model-runner design D12).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_ollama_capture.py."""

from pathlib import Path

import pytest

from ollama_capture_shared import _tool


def test_a_capture_refuses_an_endpoint_that_isnt_on_this_machine(tmp_path: Path) -> None:
    capture = _tool()
    with pytest.raises(SystemExit, match="isn't on this machine"):
        capture.capture("success-with-tools", "http://example.com:11434", tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_the_replay_starts_each_fixture_with_the_files_its_capture_made() -> None:
    from fixture_replay import FILES

    made = {name: s.files for name, s in _tool().SCENARIOS.items() if s.files}
    assert made == FILES
