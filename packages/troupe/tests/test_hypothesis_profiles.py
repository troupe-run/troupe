"""The project's hypothesis profiles (hypothesis_profiles.py, loaded for every test path)."""

import os
import subprocess
import sys
from pathlib import Path

from hypothesis import settings

ROOT = Path(__file__).resolve().parents[3]
SLOW = """\
import time
from hypothesis import Phase, given, settings, strategies as st

@settings(max_examples=3, phases=[Phase.generate])
@given(st.integers())
def test_slow(number):
    time.sleep(0.3)
"""


def test_no_profile_a_run_can_use_has_a_per_example_deadline() -> None:
    assert settings.get_profile("default").deadline is None
    assert settings.get_profile("ci").deadline is None
    assert settings().deadline is None  # whichever is active


def test_ci_still_uses_fixed_seeds_and_no_database() -> None:
    ci = settings.get_profile("ci")
    assert ci.derandomize is True
    assert ci.database is None


RECORD_DIRS = """\
import os
import pytest

def pytest_collectstart(collector):
    if isinstance(collector, pytest.Dir):
        with open(os.environ["RECORDED_DIRS"], "a", encoding="utf-8") as recorded:
            recorded.write(str(collector.path) + "\\n")
"""
"""A plugin for the child run that writes down every directory it collects."""


def run_slow(
    tmp_path: Path, config: Path, *plugins: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """A 300 ms example, run with pytest's configuration from ``config``.

    The child collects only ``tmp_path`` (``--confcutdir``). Without it, when the repository and the
    temp directory are on different drives, no directory above the test is above the repository, so
    pytest collects every one from the drive's root down, and on Windows stats each entry beside
    them, other tests' temp directories included. One removed in between failed the run (#226).
    """
    test = tmp_path / "test_slow.py"
    test.write_text(SLOW, encoding="utf-8")
    return subprocess.run(
        [
            *[sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
            *["--rootdir", str(config.parent), "-c", str(config), "-o", "testpaths="],
            *["--confcutdir", str(tmp_path)],
            *[arg for plugin in plugins for arg in ("-p", plugin)],
            *["--hypothesis-profile=default", str(test)],
        ],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
        cwd=ROOT,
        env={**os.environ, "HYPOTHESIS_STORAGE_DIRECTORY": str(tmp_path / "db"), **(env or {})},
    )


def test_a_slow_example_passes_under_the_profile_the_flake_hunt_asks_for(tmp_path: Path) -> None:
    completed = run_slow(tmp_path, ROOT / "pyproject.toml")
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_the_slow_examples_run_collects_no_directory_outside_its_own(tmp_path: Path) -> None:
    # Directories above or beside tmp_path belong to other tests, which create and remove theirs
    # while this runs (#226).
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    (plugin / "record_dirs.py").write_text(RECORD_DIRS, encoding="utf-8")
    recorded = tmp_path / "dirs.txt"
    path = os.pathsep.join(filter(None, [str(plugin), os.environ.get("PYTHONPATH")]))
    completed = run_slow(
        tmp_path,
        ROOT / "pyproject.toml",
        "record_dirs",
        env={"PYTHONPATH": path, "RECORDED_DIRS": str(recorded)},
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    collected = [Path(line) for line in recorded.read_text(encoding="utf-8").splitlines()]
    assert collected, "the child run collected no directory, so this checks nothing"
    assert [d for d in collected if not d.is_relative_to(tmp_path)] == []


def test_without_the_plugin_the_same_example_fails_on_hypothesiss_deadline(tmp_path: Path) -> None:
    # The control: hypothesis's own default profile, with no project configuration, fails it.
    bare = tmp_path / "pytest.ini"
    bare.write_text("[pytest]\n", encoding="utf-8")
    completed = run_slow(tmp_path, bare)
    assert completed.returncode == 1
    assert "DeadlineExceeded" in completed.stdout
