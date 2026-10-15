"""scripts/flake_hunt.py (spec: flake-hunt). Each test writes a few test files into a fresh root and
runs the real script over them, so every report the hunt reads is one pytest actually wrote."""

import json
import os
import queue
import signal
import subprocess
import sys
import textwrap
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import flake_hunt
from troupe.platform.processes import is_running

SCRIPT = Path(flake_hunt.__file__)
WINDOWS = sys.platform == "win32"

GRANDCHILD = """
import subprocess, sys, time
from pathlib import Path

def start_grandchild(pid_file: Path) -> None:
    # A child that starts a sleeping grandchild, waits for it to record its pid, then exits.
    code = (
        "import os, subprocess, sys, time\\n"
        "from pathlib import Path\\n"
        "target = Path(sys.argv[1])\\n"
        "grandchild = subprocess.Popen([sys.executable, '-c', "
        "'import os, sys, time; from pathlib import Path; "
        "Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(120)', str(target)])\\n"
        "deadline = time.monotonic() + 30\\n"
        "while not (target.exists() and target.read_text()):\\n"
        "    assert time.monotonic() < deadline, 'the grandchild never recorded its pid'\\n"
        "    time.sleep(0.05)\\n"
    )
    subprocess.run([sys.executable, "-c", code, str(pid_file)], check=True, timeout=60)
"""


def make_root(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "root"
    root.mkdir()
    (root / "pytest.ini").write_text("[pytest]\n")  # the root is pytest's rootdir, not the repo
    (root / "helpers.py").write_text(textwrap.dedent(GRANDCHILD))
    for name, text in files.items():
        (root / name).write_text(textwrap.dedent(text), encoding="utf-8")
    return root


def hunt_command(root: Path, out: Path, *args: str) -> list[str]:
    return [sys.executable, str(SCRIPT), "--root", str(root), "--out", str(out), *args]


def run_hunt(
    root: Path, out: Path, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        hunt_command(root, out, *args),
        capture_output=True,
        timeout=120,
        check=False,
        env=env,
        cwd=root,
    )


def summary(out: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    return data


def results(out: Path) -> list[dict[str, Any]]:
    lines = (out / "results.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def text(completed: subprocess.CompletedProcess[bytes]) -> str:
    return completed.stdout.decode("utf-8", errors="backslashreplace")


def gone_within(pids: list[int], seconds: float) -> list[int]:
    """The pids still running after ``seconds`` (an orphan can take a moment to be reaped)."""
    deadline = time.monotonic() + seconds
    while True:
        alive = [pid for pid in pids if is_running(pid)]
        if not alive or time.monotonic() >= deadline:
            return alive
        time.sleep(0.1)


def pids_in(directory: Path) -> list[int]:
    return [int(path.read_text()) for path in sorted(directory.glob("*.pid"))]


PASSING = {"test_one.py": "def test_passes():\n    pass\n"}


# Requirement: The hunt refuses malformed options


@pytest.mark.parametrize(
    ("args", "named"),
    [
        (["--rounds", "0"], "--rounds: '0' isn't allowed"),
        (["--workers", "0"], "--workers: '0' isn't allowed"),
        (["--load", "-1"], "--load: '-1' isn't allowed"),
        (["--rounds", "two"], "--rounds: 'two' isn't allowed"),
        (["--rounds", "1.5"], "--rounds: '1.5' isn't allowed"),
        (["--round-timeout", "0"], "--round-timeout: '0' isn't allowed"),
        (["--stall", "-1"], "--stall: '-1' isn't allowed"),
        (["--load", str(flake_hunt.usable_cpus() + 1)], "lets the hunt use"),
        (["missing_test.py"], "'missing_test.py' doesn't exist"),
    ],
)
def test_a_malformed_option_is_refused_naming_it_and_nothing_runs(
    tmp_path: Path, args: list[str], named: str
) -> None:
    root = make_root(tmp_path, PASSING)
    out = tmp_path / "out"
    completed = run_hunt(root, out, *args)
    assert completed.returncode == 2
    assert named in completed.stderr.decode()
    assert not out.exists()


def test_workers_auto_is_three_quarters_of_the_usable_cpus_less_the_load_and_at_least_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cases = (
        (8, 0, 6),
        (8, 2, 4),
        (10, 0, 7),
        (10, 2, 5),
        (4, 0, 3),
        (4, 3, 1),
        (1, 0, 1),
        (2, 1, 1),
    )
    for cpus, load, workers in cases:
        monkeypatch.setattr(flake_hunt, "usable_cpus", lambda cpus=cpus: cpus)
        chosen = flake_hunt.parse_options(
            ["--root", str(tmp_path), "--workers", "auto", "--load", str(load)]
        )
        assert chosen.workers == workers, (cpus, load)
    assert flake_hunt.parse_workers("5") == 5
    with pytest.raises(Exception, match="--workers must be a whole number, 1 or more, or auto"):
        flake_hunt.parse_workers("lots")


# Requirement: The hunt repeats tests in overlapping rounds


def test_two_workers_of_two_rounds_run_four_rounds_and_a_tmp_path_test_passes_in_each(
    tmp_path: Path,
) -> None:
    root = make_root(tmp_path, {"test_tmp.py": "def test_uses_tmp_path(tmp_path):\n    pass\n"})
    out = tmp_path / "out"
    completed = run_hunt(root, out, "--workers", "2", "--rounds", "2")
    assert completed.returncode == 0, text(completed)
    rounds = results(out)
    assert sorted(each["round"] for each in rounds) == ["w0r0", "w0r1", "w1r0", "w1r1"]
    assert {each["status"] for each in rounds} == {"passed"}
    assert {each["tests"] for each in rounds} == {1}
    assert "4 rounds ran, 0 failed." in text(completed)


def test_the_workers_rounds_overlap(tmp_path: Path) -> None:
    started = tmp_path / "started"
    started.mkdir()
    root = make_root(
        tmp_path,
        {
            "test_overlap.py": f"""
            import os, time
            from pathlib import Path

            def test_waits_for_the_other_worker():
                here = Path({str(started)!r})
                (here / str(os.getpid())).write_text("")
                deadline = time.monotonic() + 30
                while len(list(here.iterdir())) < 2:
                    assert time.monotonic() < deadline, "the other worker's round never started"
                    time.sleep(0.05)
            """
        },
    )
    completed = run_hunt(root, tmp_path / "out", "--workers", "2")
    assert completed.returncode == 0, text(completed)


def test_a_path_and_a_keyword_select_exactly_what_pytest_selects(tmp_path: Path) -> None:
    root = make_root(
        tmp_path,
        {
            "test_a.py": "def test_apple():\n    pass\n\ndef test_banana():\n    pass\n",
            "test_b.py": "def test_cherry():\n    assert False\n",
        },
    )
    out = tmp_path / "out"
    completed = run_hunt(root, out, "-k", "apple", "test_a.py")
    assert completed.returncode == 0, text(completed)
    assert [each["tests"] for each in results(out)] == [1]
    everything = run_hunt(root, tmp_path / "all")
    assert [each["tests"] for each in results(tmp_path / "all")] == [3]
    assert everything.returncode == 1


def test_a_round_gets_the_hunts_environment_plus_only_its_hypothesis_directory(
    tmp_path: Path,
) -> None:
    options = flake_hunt.parse_options(["--root", str(tmp_path), "--out", str(tmp_path / "out")])
    env = flake_hunt.round_environment(options, "w0r0")
    assert {name: value for name, value in env.items() if name in os.environ} == dict(os.environ)
    assert set(env) - set(os.environ) == {"HYPOTHESIS_STORAGE_DIRECTORY"}
    assert env["HYPOTHESIS_STORAGE_DIRECTORY"] == str(tmp_path / "out" / "hypothesis" / "w0r0")


# Requirement: The hunt reports each failing test with its evidence


def test_a_test_failing_in_alternate_rounds_is_summarised_with_its_runs_and_failures(
    tmp_path: Path,
) -> None:
    counter = tmp_path / "count"
    root = make_root(
        tmp_path,
        {
            "test_flaky.py": f"""
            from pathlib import Path

            def test_fails_every_other_run():
                counter = Path({str(counter)!r})
                runs = int(counter.read_text()) if counter.exists() else 0
                counter.write_text(str(runs + 1))
                assert runs % 2 == 0, "an odd run"

            def test_always_passes():
                pass
            """
        },
    )
    out = tmp_path / "out"
    completed = run_hunt(root, out, "--rounds", "4")
    assert completed.returncode == 1
    found = summary(out)
    assert (found["roundsRun"], found["roundsFailed"]) == (4, 2)
    [flaky] = found["tests"]
    assert flaky["test"] == "test_flaky.py::test_fails_every_other_run"
    assert (flaky["runs"], flaky["failures"], flaky["firstRound"]) == (4, 2, "w0r1")
    assert "an odd run" in flaky["message"]
    assert "def test_fails_every_other_run" in flaky["traceback"]
    output = text(completed)
    assert "FAILED test_flaky.py::test_fails_every_other_run: 2 of 4 runs" in output
    assert "an odd run" in output
    assert [each["status"] for each in results(out)] == ["passed", "failed", "passed", "failed"]
    for name in ("w0r0.log", "w0r0.xml", "w0r3.log", "w0r3.xml"):
        assert (out / "rounds" / name).is_file()


def test_a_test_in_a_class_and_an_erroring_fixture_are_named_by_their_pytest_ids(
    tmp_path: Path,
) -> None:
    root = make_root(
        tmp_path,
        {
            "test_shapes.py": """
            import pytest

            @pytest.fixture
            def broken():
                raise RuntimeError("the fixture broke")

            def test_uses_broken(broken):
                pass

            class TestGroup:
                def test_inside(self):
                    assert 1 == 2
            """
        },
    )
    out = tmp_path / "out"
    run_hunt(root, out)
    found = {each["test"]: each for each in summary(out)["tests"]}
    assert set(found) == {
        "test_shapes.py::test_uses_broken",
        "test_shapes.py::TestGroup::test_inside",
    }
    assert "the fixture broke" in found["test_shapes.py::test_uses_broken"]["traceback"]
    [record] = results(out)
    kinds = {failure["test"]: failure["kind"] for failure in record["failures"]}
    assert kinds["test_shapes.py::test_uses_broken"] == "error"
    assert kinds["test_shapes.py::TestGroup::test_inside"] == "failure"


def test_a_round_that_crashes_without_a_report_is_failed_with_the_end_of_its_output(
    tmp_path: Path,
) -> None:
    root = make_root(
        tmp_path,
        {
            "conftest.py": """
            import os, sys

            def pytest_collection_finish(session):
                sys.__stderr__.write("about to crash\\n")
                sys.__stderr__.flush()
                os._exit(3)
            """,
            **PASSING,
        },
    )
    out = tmp_path / "out"
    completed = run_hunt(root, out)
    assert completed.returncode == 1
    [record] = results(out)
    assert (record["status"], record["exitCode"]) == ("crashed", 3)
    found = summary(out)
    assert found["roundsFailed"] == 1
    assert [each["round"] for each in found["roundsWithoutReport"]] == ["w0r0"]
    assert "Round w0r0 crashed (exit code 3)" in text(completed)


def test_a_round_that_collects_nothing_is_failed_not_passed(tmp_path: Path) -> None:
    root = make_root(tmp_path, PASSING)
    out = tmp_path / "out"
    completed = run_hunt(root, out, "-k", "no_such_test")
    assert completed.returncode == 1
    [record] = results(out)
    assert (record["status"], record["exitCode"]) == ("crashed", 5)


def test_output_that_isnt_utf_8_is_kept_as_bytes_and_shown_escaped(tmp_path: Path) -> None:
    log = tmp_path / "w0r0.log"
    log.write_bytes(b"before \xff\xfe after\n")
    assert flake_hunt.tail(log) == "before \\xff\\xfe after\n"


def test_a_clean_hunt_says_none_failed_and_exits_0(tmp_path: Path) -> None:
    root = make_root(tmp_path, PASSING)
    out = tmp_path / "out"
    completed = run_hunt(root, out, "--rounds", "2")
    assert completed.returncode == 0
    assert "2 rounds ran, 0 failed." in text(completed)
    assert summary(out)["tests"] == []
    assert f"Results: {out}" in text(completed)


# Requirement: The hunt runs on every platform (text the console can't show)


def test_a_failure_the_console_cant_encode_still_prints_escaped_and_is_kept_whole(
    tmp_path: Path,
) -> None:
    root = make_root(
        tmp_path,
        {"test_text.py": 'def test_text():\n    assert "ünïcødé ✓" == ""\n'},
    )
    out = tmp_path / "out"
    env = dict(os.environ, PYTHONIOENCODING="cp1252")
    completed = run_hunt(root, out, env=env)
    assert completed.returncode == 1
    printed = completed.stdout.decode("cp1252")
    assert "FAILED test_text.py::test_text: 1 of 1 runs" in printed
    assert "ünïcødé \\u2713" in printed
    assert "ünïcødé ✓" in summary(out)["tests"][0]["message"]


# Requirement: Every round explores new randomised inputs


def test_each_round_has_a_private_hypothesis_database_and_the_roots_is_untouched(
    tmp_path: Path,
) -> None:
    root = make_root(
        tmp_path,
        {
            "test_property.py": """
            from hypothesis import given, strategies as st

            @given(st.integers())
            def test_always_fails(number):
                assert number != number
            """
        },
    )
    out = tmp_path / "out"
    run_hunt(root, out, "--rounds", "2")
    [found] = summary(out)["tests"]
    assert (found["runs"], found["failures"]) == (2, 2)
    assert "number=0" in found["traceback"]  # the falsifying example, as hypothesis reports it
    for tag in ("w0r0", "w0r1"):
        assert any((out / "hypothesis" / tag).rglob("*")), f"{tag} saved nothing in its database"
    assert not (root / ".hypothesis").exists()


# Requirement: Nothing a round starts outlives it


def test_a_grandchild_left_by_a_passing_round_is_stopped_when_the_round_ends(
    tmp_path: Path,
) -> None:
    pids = tmp_path / "pids"
    pids.mkdir()
    root = make_root(
        tmp_path,
        {
            "test_leaves.py": f"""
            import os
            from pathlib import Path
            from helpers import start_grandchild

            def test_leaves_a_grandchild():
                start_grandchild(Path({str(pids)!r}) / f"{{os.getpid()}}.pid")
            """
        },
    )
    completed = run_hunt(root, tmp_path / "out", "--rounds", "2")
    assert completed.returncode == 0, text(completed)
    left = pids_in(pids)
    assert len(left) == 2
    assert gone_within(left, 5) == []


def test_a_round_past_its_timeout_is_stopped_reported_hung_and_the_next_still_runs(
    tmp_path: Path,
) -> None:
    pids = tmp_path / "pids"
    pids.mkdir()
    root = make_root(
        tmp_path,
        {
            "test_hangs.py": f"""
            import os, time
            from pathlib import Path
            from helpers import start_grandchild

            def test_hangs():
                start_grandchild(Path({str(pids)!r}) / f"{{os.getpid()}}.pid")
                time.sleep(120)
            """
        },
    )
    out = tmp_path / "out"
    started = time.monotonic()
    completed = run_hunt(root, out, "--rounds", "2", "--round-timeout", "4")
    elapsed = time.monotonic() - started
    assert completed.returncode == 1
    assert [(each["round"], each["status"]) for each in results(out)] == [
        ("w0r0", "hung"),
        ("w0r1", "hung"),
    ]
    assert elapsed < 2 * 4 + 20, f"two 4 s rounds took {elapsed:.1f}s"
    assert "Round w0r1 hung" in text(completed)
    assert gone_within(pids_in(pids), 5) == []


def test_a_test_stuck_past_the_stall_limit_has_its_stack_in_the_hung_rounds_output(
    tmp_path: Path,
) -> None:
    root = make_root(
        tmp_path,
        {"test_stuck.py": "import time\n\ndef test_stuck_here():\n    time.sleep(120)\n"},
    )
    out = tmp_path / "out"
    completed = run_hunt(root, out, "--stall", "2", "--round-timeout", "8")
    assert completed.returncode == 1
    [record] = results(out)
    assert record["status"] == "hung"
    assert "Timeout (0:00:02)!" in record["outputTail"]
    assert "in test_stuck_here" in record["outputTail"]


# Requirement: The hunt can load the machine


def test_the_load_runs_during_the_rounds_and_is_gone_when_the_hunt_returns(
    tmp_path: Path,
) -> None:
    out = tmp_path / "out"
    root = make_root(
        tmp_path,
        {
            "test_load.py": f"""
            import json
            from pathlib import Path
            from troupe.platform.processes import is_running

            def test_the_load_is_running():
                pids = json.loads((Path({str(out)!r}) / "load.json").read_text())["pids"]
                assert len(pids) == 2
                assert all(is_running(pid) for pid in pids)
            """
        },
    )
    completed = run_hunt(root, out, "--load", "2", "--rounds", "2")
    assert completed.returncode == 0, text(completed)
    load = summary(out)["loadPids"]
    assert len(load) == 2
    assert gone_within(load, 5) == []


# Stopping part-way (Ctrl-C, or Ctrl-Break on Windows)


def test_a_round_killed_by_a_stop_is_not_recorded_as_a_crash(tmp_path: Path) -> None:
    root = make_root(
        tmp_path, {"test_sleeps.py": "import time\n\ndef test_sleeps():\n    time.sleep(120)\n"}
    )
    options = flake_hunt.parse_options(["--root", str(root), "--out", str(tmp_path / "out")])
    (options.out / "rounds").mkdir(parents=True)
    stop = threading.Event()
    running = flake_hunt._Running()
    outcome: list[flake_hunt.Round | None] = []
    worker = threading.Thread(
        target=lambda: outcome.append(flake_hunt.run_round(options, tmp_path, 0, 0, stop, running))
    )
    worker.start()
    deadline = time.monotonic() + 30
    while not running._trees:
        assert time.monotonic() < deadline, "the round never started"
        time.sleep(0.05)
    stop.set()  # as the hunt's main thread does: the flag first, then the kill
    running.stop_all()
    worker.join(30)
    assert outcome == [None]


class Lines:
    """The hunt's output, read on a thread so a test can wait for a line with a deadline."""

    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self.seen: list[str] = []
        self._queue: queue.Queue[str | None] = queue.Queue()
        assert process.stdout is not None
        stream = process.stdout

        def read() -> None:
            for line in iter(stream.readline, b""):
                self._queue.put(line.decode("utf-8", errors="backslashreplace"))
            self._queue.put(None)

        threading.Thread(target=read, daemon=True).start()

    def wait_for(self, wanted: Callable[[str], bool], seconds: float) -> str:
        deadline = time.monotonic() + seconds
        while (left := deadline - time.monotonic()) > 0:
            try:
                line = self._queue.get(timeout=left)
            except queue.Empty:
                break
            if line is None:
                break
            self.seen.append(line)
            if wanted(line):
                return line
        raise AssertionError(f"no such line within {seconds}s; saw: {''.join(self.seen)}")

    def rest(self, seconds: float) -> str:
        with_rest = list(self.seen)
        deadline = time.monotonic() + seconds
        while (left := deadline - time.monotonic()) > 0:
            try:
                line = self._queue.get(timeout=left)
            except queue.Empty:
                break
            if line is None:
                break
            with_rest.append(line)
        return "".join(with_rest)


HANGS_AFTER_ITS_FIRST_RUN = """
import os, time
from pathlib import Path
from helpers import start_grandchild

def test_passes_once_then_hangs():
    counter = Path({counter!r})
    if not counter.exists():
        counter.write_text("1")
        return
    start_grandchild(Path({pids!r}) / f"{{os.getpid()}}.pid")
    time.sleep(120)
"""


def start_hunt(root: Path, out: Path, *args: str) -> subprocess.Popen[bytes]:
    if WINDOWS:
        return subprocess.Popen(
            hunt_command(root, out, *args),
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,  # type: ignore[attr-defined,unused-ignore]
        )
    return subprocess.Popen(
        hunt_command(root, out, *args),
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def hanging_root(tmp_path: Path) -> tuple[Path, Path]:
    pids = tmp_path / "pids"
    pids.mkdir()
    counter = tmp_path / "count"
    root = make_root(
        tmp_path,
        {"test_hang.py": HANGS_AFTER_ITS_FIRST_RUN.format(counter=str(counter), pids=str(pids))},
    )
    return root, pids


def wait_for_pid_file(pids: Path, seconds: float) -> list[int]:
    deadline = time.monotonic() + seconds
    while not (found := [p for p in pids.glob("*.pid") if p.read_text()]):
        assert time.monotonic() < deadline, "the hanging round never started its grandchild"
        time.sleep(0.05)
    return [int(path.read_text()) for path in found]


def test_an_interrupt_stops_the_rounds_and_the_load_and_summarises_what_finished(
    tmp_path: Path,
) -> None:
    root, pids = hanging_root(tmp_path)
    out = tmp_path / "out"
    hunt = start_hunt(root, out, "--rounds", "3", "--load", "1")
    lines = Lines(hunt)
    try:
        lines.wait_for(lambda line: line.startswith("w0r0 passed"), 60)
        grandchildren = wait_for_pid_file(pids, 60)
        interrupted = time.monotonic()
        if WINDOWS:
            os.kill(hunt.pid, signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined,unused-ignore]
        else:
            os.kill(hunt.pid, signal.SIGINT)
        output = lines.rest(10)
        hunt.wait(10)
        stopped_in = time.monotonic() - interrupted
    finally:
        hunt.kill()
    assert stopped_in < 5, f"the hunt took {stopped_in:.1f}s to stop"
    assert hunt.returncode == 130, output
    assert "flake_hunt: stopping" in output
    assert "1 round ran (stopped part-way), 0 failed." in output
    assert [each["round"] for each in results(out)] == ["w0r0"]
    assert summary(out)["stopped"] is True
    assert gone_within(grandchildren + summary(out)["loadPids"], 5) == []


@pytest.mark.skipif(not WINDOWS, reason="Ctrl-C as a console event is Windows' own")
def test_on_windows_a_rounds_tests_still_get_a_real_ctrl_c(tmp_path: Path) -> None:
    # A round started in a new process group has Ctrl-C turned off, and so does everything it
    # starts: this test failed in every round of the owner's first Windows hunt (#100).
    real = (
        "packages/troupe/tests/test_platform_interrupts.py"
        "::test_a_real_ctrl_c_on_windows_calls_back_too"
    )
    out = tmp_path / "out"
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--out", str(out), real],
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, text(completed)
    assert [each["tests"] for each in results(out)] == [1]


@pytest.mark.skipif(not WINDOWS, reason="a killed hunt ends its rounds through a Windows job")
def test_on_windows_killing_the_hunt_itself_ends_its_rounds_trees(tmp_path: Path) -> None:
    root, pids = hanging_root(tmp_path)
    hunt = start_hunt(root, tmp_path / "out", "--rounds", "3")
    lines = Lines(hunt)
    try:
        first = lines.wait_for(lambda line: line.startswith("flake_hunt: pid "), 60)
        hunt_pid = int(first.split()[2].rstrip(","))  # the interpreter, not the venv's launcher
        lines.wait_for(lambda line: line.startswith("w0r0 passed"), 60)
        grandchildren = wait_for_pid_file(pids, 60)
        os.kill(hunt_pid, signal.SIGTERM)  # TerminateProcess: no finally runs in the hunt
        hunt.wait(30)
    finally:
        hunt.kill()
    assert gone_within(grandchildren, 10) == []
