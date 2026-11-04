"""The stand-in check fails a test that leaves a stand-in claude running, and stops it (spec:
claude-code-runner, "A test that leaves a stand-in running fails"; reap-fake-claude design D3).

Each case runs a child pytest in ``tmp_path`` whose conftest loads the check, so the check judges
the child's tests, not these.
"""

import contextlib
import json
import os
import signal
import subprocess
import sys
import textwrap
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from claude_harness import alive

HERE = Path(__file__).resolve().parent
TIMEOUT = 240.0
"""How long a child pytest may take. Generous: on a loaded machine one took 90 s, and a child
killed by the timeout never runs its sweep."""

CONFTEST = f"""
import sys
sys.path.insert(0, {str(HERE)!r})
from stand_in_guard import pytest_configure, pytest_runtest_teardown, pytest_unconfigure
"""

HELPERS = f"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from fake_claude import install

STAND_IN = {str(HERE / "fake_claude.py")!r}


def hanging(tmp_path, name):
    '''Start a hanging stand-in through its shim, and return its pid once it has recorded it.'''
    record = tmp_path / "record.json"
    shim = install(tmp_path / "bin")
    env = {{**os.environ, "FAKE_CLAUDE_HANG": "1", "FAKE_CLAUDE_RECORD": str(record)}}
    subprocess.Popen(
        [str(shim)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, env=env, cwd=tmp_path
    )
    while not record.exists():
        time.sleep(0.02)
    pid = json.loads(record.read_text(encoding="utf-8"))["pid"]
    Path(os.environ["PIDS"], name).write_text(str(pid), encoding="utf-8")
    return pid


def hanging_later(tmp_path, name, go):
    '''Start a hanging stand-in once the file ``go`` exists, from a process this test leaves behind,
    as one that escaped its runner's process group before it recorded itself would. Waiting for a
    file another test makes, not a delay, so it records itself only after this test's check.'''
    env = {{**os.environ, "FAKE_CLAUDE_HANG": "1",
            "FAKE_CLAUDE_RECORD": str(Path(os.environ["PIDS"], name + ".json"))}}
    launch = (
        "import os, subprocess, sys, time\\n"
        "deadline = time.monotonic() + 60\\n"
        "while not os.path.exists(sys.argv[1]) and time.monotonic() < deadline:\\n"
        "    time.sleep(0.02)\\n"
        "subprocess.Popen([sys.executable, sys.argv[2]], stdin=subprocess.DEVNULL)\\n"
    )
    subprocess.Popen([sys.executable, "-c", launch, str(go), STAND_IN], env=env, cwd=tmp_path)
"""


@pytest.fixture
def pids(tmp_path: Path) -> Iterator[Path]:
    """Where the child's tests write their stand-ins' pids. If a case fails and leaves one of
    them running, it's stopped here, so a failing case doesn't leak what it was testing for."""
    path = tmp_path / "pids"
    path.mkdir()
    yield path
    for entry in path.iterdir():
        with contextlib.suppress(ValueError, OSError):  # not written whole, or already gone
            pid = _pid(path, entry.name)
            if alive(pid):  # written by the stand-in during this test, so still its pid
                os.kill(pid, signal.SIGKILL if sys.platform != "win32" else signal.SIGTERM)


def _child(tmp_path: Path, pids: Path, tests: str) -> subprocess.CompletedProcess[str]:
    """Run ``tests`` in a child pytest with the check loaded, its tests writing their stand-ins'
    pids into ``pids``."""
    child = tmp_path / "child"
    child.mkdir()
    (child / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (child / "conftest.py").write_text(CONFTEST, encoding="utf-8")
    (child / "helpers.py").write_text(HELPERS, encoding="utf-8")
    (child / "test_child.py").write_text(textwrap.dedent(tests), encoding="utf-8")
    env = {name: value for name, value in os.environ.items() if name != "FAKE_CLAUDE_LEDGER"}
    env["PIDS"] = str(pids)
    env["PYTHONPATH"] = str(child)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"  # it needs no installed plugin, only the check
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--confcutdir",
            str(child),
            "-c",
            str(child / "pytest.ini"),
            str(child / "test_child.py"),
        ],
        cwd=child,
        env=env,
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
        check=False,
    )
    return done


def _pid(pids: Path, name: str) -> int:
    path = pids / name
    if path.suffix == ".json":
        return int(json.loads(path.read_text(encoding="utf-8"))["pid"])
    return int(path.read_text(encoding="utf-8"))


def _gone(pid: int) -> bool:
    deadline = time.monotonic() + 30
    while alive(pid):
        if time.monotonic() > deadline:
            return False
        time.sleep(0.05)
    return True


def test_a_test_that_leaves_a_hanging_stand_in_fails_naming_it_and_the_stand_in_is_stopped(
    tmp_path: Path, pids: Path
) -> None:
    done = _child(
        tmp_path,
        pids,
        """
        from helpers import hanging

        def test_leaves_it(tmp_path):
            hanging(tmp_path, "leaked")
        """,
    )
    pid = _pid(pids, "leaked")
    assert _gone(pid), f"the stand-in {pid} is still running"
    assert done.returncode == 1, done.stdout
    assert "ERROR at teardown of test_leaves_it" in done.stdout
    assert f"stand-in claude {pid} (working directory " in done.stdout
    assert "test_leaves_it0" in done.stdout  # its working directory is the test's own
    assert "it has been stopped" in done.stdout


def test_a_test_whose_stand_in_ended_passes(tmp_path: Path, pids: Path) -> None:
    done = _child(
        tmp_path,
        pids,
        """
        import os
        import subprocess

        from fake_claude import install

        def test_runs_it_to_the_end(tmp_path):
            shim = install(tmp_path / "bin")
            subprocess.run([str(shim)], input=b"", check=True, timeout=60)
        """,
    )
    assert done.returncode == 0, done.stdout
    assert "1 passed" in done.stdout


def test_a_stand_in_that_records_itself_after_its_test_fails_the_next_test_naming_it(
    tmp_path: Path, pids: Path
) -> None:
    done = _child(
        tmp_path,
        pids,
        """
        import os
        import time
        from pathlib import Path

        from helpers import hanging_later

        def test_a_starts_one_late(tmp_path):
            hanging_later(tmp_path, "late", Path(os.environ["PIDS"], "go"))

        def test_b_runs_while_it_starts():
            Path(os.environ["PIDS"], "go").touch()  # after test_a's check, however slow that was
            record = Path(os.environ["PIDS"], "late.json")
            deadline = time.monotonic() + 60
            while not record.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
        """,
    )
    pid = _pid(pids, "late.json")
    assert _gone(pid), f"the stand-in {pid} is still running"
    assert done.returncode == 1, done.stdout
    assert "ERROR at teardown of test_b_runs_while_it_starts" in done.stdout
    assert f"stand-in claude {pid} (working directory " in done.stdout
    assert "test_a_starts_one_late0" in done.stdout  # the directory names the test it came from


def test_a_stand_in_still_running_when_the_run_ends_is_stopped(tmp_path: Path, pids: Path) -> None:
    done = _child(
        tmp_path,
        pids,
        """
        import pytest

        from helpers import hanging

        def test_stops_the_run_mid_test(tmp_path):
            hanging(tmp_path, "running")
            pytest.exit("ending the run before the test's teardown")
        """,
    )
    pid = _pid(pids, "running")
    assert _gone(pid), f"the stand-in {pid} is still running: {done.stdout}"
    assert "ending the run before the test's teardown" in done.stdout
