"""What test_config_files.py and test_config_files_integration.py share."""

from pathlib import Path
from typing import Any

from configtesting import TESTER

CONFIG: dict[str, Any] = {"actors": {"tester": TESTER}}


def _theatre(tmp_path: Path) -> Path:
    (tmp_path / ".troupe").mkdir()
    return tmp_path


def _actor_file(theatre: Path) -> Path:
    return theatre / ".troupe" / "actors" / "tester.yaml"
