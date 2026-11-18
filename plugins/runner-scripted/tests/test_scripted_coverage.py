"""A runner run under coverage, as CI's coverage leg runs every runner its tests start, saves what
it measured although it ends by os._exit (spec: plugin-sdk; quality-gates design D6)."""

import os
import subprocess
import sys
from pathlib import Path

import coverage

import troupe_runner_scripted.runner as runner


def test_the_scripted_runners_own_coverage_is_saved_when_it_exits(tmp_path: Path) -> None:
    data = tmp_path / "coverage.data"
    done = subprocess.run(
        [sys.executable, "-m", "coverage", "run", f"--data-file={data}", "-m",
         "troupe_runner_scripted"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        # Not the repository's directory, whose coverage settings would add a suffix to the file,
        # and none of this run's coverage variables, which would measure the child twice.
        cwd=tmp_path,
        env={k: v for k, v in os.environ.items() if not k.startswith("COVERAGE_")},
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    measured = coverage.CoverageData(basename=str(data))
    measured.read()
    source = Path(runner.__file__).resolve()
    lines = measured.lines(str(source)) or []
    # With standard input closed the runner ends at once, through exit_now: that line was saved.
    exit_line = 1 + source.read_text(encoding="utf-8").splitlines().index(
        "    exit_now(code)  # the reader thread may still be blocked on standard input"
    )
    assert exit_line in lines
