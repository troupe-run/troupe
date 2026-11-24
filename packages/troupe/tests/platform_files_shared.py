"""What test_platform_files.py and test_platform_files_integration.py share."""

import sys
from pathlib import Path

WINDOWS = sys.platform == "win32"


def _only_the_target_is_left(directory: Path, target: Path) -> None:
    assert sorted(directory.iterdir()) == [target]
