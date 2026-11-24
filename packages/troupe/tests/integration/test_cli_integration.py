"""The installed troupe console script, run as its own process from a directory with no theatre,
prints the installed version, writes nothing to standard error and creates no theatre (spec:
cli).

Its tests that stay in their own process are in unit/test_cli.py."""

import shutil
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

from cli_shared import VERSION_LINE
from troupe.core.exit_codes import ExitCode


def test_version_flag_prints_the_installed_version_from_a_directory_with_no_theatre(
    tmp_path: Path,
) -> None:
    executable = shutil.which("troupe", path=str(Path(sys.executable).parent))
    assert executable is not None, "the troupe console script is not installed in this environment"
    result = subprocess.run(
        [executable, "--version"], cwd=tmp_path, capture_output=True, text=True, check=False
    )
    assert not (tmp_path / ".troupe").exists()
    assert result.returncode == ExitCode.OK
    assert version("troupe") in result.stdout
    assert result.stdout == VERSION_LINE
    assert result.stderr == ""
