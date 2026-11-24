"""What test_claude_code_runner.py and test_claude_code_runner_unit.py share."""

from pathlib import Path

import pytest


@pytest.fixture(name="record")
def record_fixture(tmp_path: Path) -> Path:
    return tmp_path / "record.json"
