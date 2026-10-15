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


def run_slow(tmp_path: Path, config: Path) -> subprocess.CompletedProcess[str]:
    """A 300 ms example, run with pytest's configuration from ``config``."""
    test = tmp_path / "test_slow.py"
    test.write_text(SLOW, encoding="utf-8")
    return subprocess.run(
        [
            *[sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
            *["--rootdir", str(config.parent), "-c", str(config), "-o", "testpaths="],
            *["--hypothesis-profile=default", str(test)],
        ],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
        cwd=ROOT,
        env={**os.environ, "HYPOTHESIS_STORAGE_DIRECTORY": str(tmp_path / "db")},
    )


def test_a_slow_example_passes_under_the_profile_the_flake_hunt_asks_for(tmp_path: Path) -> None:
    completed = run_slow(tmp_path, ROOT / "pyproject.toml")
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_without_the_plugin_the_same_example_fails_on_hypothesiss_deadline(tmp_path: Path) -> None:
    # The control: hypothesis's own default profile, with no project configuration, fails it.
    bare = tmp_path / "pytest.ini"
    bare.write_text("[pytest]\n", encoding="utf-8")
    completed = run_slow(tmp_path, bare)
    assert completed.returncode == 1
    assert "DeadlineExceeded" in completed.stdout
