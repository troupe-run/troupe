"""exit_now is os._exit, except that a running coverage.py saves first (spec: plugin-sdk;
quality-gates design D6)."""

import json
import os
import subprocess
import sys
from pathlib import Path

import coverage

SCRIPT = """\
import atexit, sys
atexit.register(lambda: print("atexit ran", flush=True))
from troupe_plugin_sdk.process import exit_now

def measured():
    return "measured"

measured()
print(json.dumps({"coverage loaded": "coverage" in sys.modules}), flush=True)
exit_now(3)
print("after exit_now", flush=True)
"""


def without_coverage_variables() -> dict[str, str]:
    """This process's environment, without what would start coverage.py in a child."""
    return {k: v for k, v in os.environ.items() if not k.startswith("COVERAGE_")}


def test_without_coverage_it_is_exactly_os_exit(tmp_path: Path) -> None:
    script = tmp_path / "runner.py"
    script.write_text("import json\n" + SCRIPT, encoding="utf-8")
    done = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        check=False,
        env=without_coverage_variables(),
    )
    assert done.returncode == 3, done.stderr
    # The helper never imports coverage.py, and, as with os._exit, nothing after it or at exit runs.
    assert done.stdout.splitlines() == [json.dumps({"coverage loaded": False})]


def test_under_coverage_the_process_saves_what_it_measured(tmp_path: Path) -> None:
    script = tmp_path / "runner.py"
    script.write_text("import json\n" + SCRIPT, encoding="utf-8")
    data = tmp_path / "coverage.data"
    done = subprocess.run(
        [sys.executable, "-m", "coverage", "run", f"--data-file={data}", str(script)],
        capture_output=True,
        text=True,
        check=False,
        env=without_coverage_variables(),
        # Not the repository's directory, whose coverage settings would add a suffix to the file.
        cwd=tmp_path,
    )
    assert done.returncode == 3, done.stderr
    assert "atexit ran" not in done.stdout
    measured = coverage.CoverageData(basename=str(data))
    measured.read()
    lines = measured.lines(str(script.resolve())) or measured.lines(str(script)) or []
    # The function body ran, and coverage.py saved it although the process ended by os._exit.
    body = 1 + SCRIPT.splitlines().index('    return "measured"') + 1
    assert body in lines
