"""Tests for child processes (spec: platform)."""

import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

from troupe.platform import processes
from troupe.platform.errors import (
    CommandNotFoundError,
    LineTooLongError,
    OutputTooLargeError,
    ProcessTimeoutError,
)

WINDOWS = sys.platform == "win32"
LIMIT = 8 * 1024 * 1024

ADDED_BY_THE_INTERPRETER = {"LC_CTYPE", "__CF_USER_TEXT_ENCODING", "__PYVENV_LAUNCHER__"}
"""Variables a Python child sets in its own environment at start-up (locale coercion, macOS
CoreFoundation, the Windows venv launcher), so they are not evidence of inheritance."""


def _python(code: str) -> list[str]:
    return [sys.executable, "-c", code]


async def _output(child: processes.ChildProcess) -> bytes:
    out = await child.stdout.read()
    await child.wait()
    child.release()
    return out


def _child_environment(env: dict[str, str]) -> dict[str, str]:
    async def main() -> bytes:
        child = await processes.start(
            _python("import json, os; print(json.dumps(dict(os.environ)))"),
            cwd=Path.cwd(),
            env=env,
            line_limit=LIMIT,
        )
        return await _output(child)

    seen: dict[str, str] = json.loads(asyncio.run(main()))
    return seen


# Requirement: Child processes start in their own group with an explicit environment


def test_a_child_sees_the_named_variable_and_none_of_the_parents_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TROUPE_TEST_HOST_SECRET", "must-not-leak")
    seen = _child_environment({"TROUPE_TEST_NAMED": "passed"})
    assert seen["TROUPE_TEST_NAMED"] == "passed"
    assert "TROUPE_TEST_HOST_SECRET" not in seen
    unexpected = set(seen) - {"TROUPE_TEST_NAMED", *processes.MINIMUM_ENVIRONMENT}
    assert unexpected <= ADDED_BY_THE_INTERPRETER


def test_a_python_child_starts_and_runs_with_no_named_variables() -> None:
    seen = _child_environment({})
    assert set(seen) - set(processes.MINIMUM_ENVIRONMENT) <= ADDED_BY_THE_INTERPRETER
    if WINDOWS:
        assert "SYSTEMROOT" in seen


def test_a_missing_command_is_reported_by_name() -> None:
    async def main() -> None:
        await processes.start(["troupe-no-such-runner"], cwd=Path.cwd(), env={}, line_limit=LIMIT)

    with pytest.raises(CommandNotFoundError) as caught:
        asyncio.run(main())
    assert caught.value.command == "troupe-no-such-runner"


def test_the_command_is_found_on_the_given_search_path(tmp_path: Path) -> None:
    found = processes.resolve_command(Path(sys.executable).name, str(Path(sys.executable).parent))
    assert Path(found).is_absolute()
    with pytest.raises(CommandNotFoundError):
        processes.resolve_command(Path(sys.executable).name, str(tmp_path))


# Requirement: Killing a child kills its whole process tree

GRANDPARENT = """
import subprocess, sys, time
grandchild = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
print(grandchild.pid, flush=True)
time.sleep(120)
"""


def _gone_within(pid: int, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not processes.is_running(pid):
            return True
        time.sleep(0.05)
    return False


def test_killing_a_child_also_kills_the_grandchild_it_started() -> None:
    async def main() -> tuple[int, int]:
        child = await processes.start(
            _python(GRANDPARENT), cwd=Path.cwd(), env={}, line_limit=LIMIT
        )
        grandchild = int(await asyncio.wait_for(child.stdout.readline(), timeout=30))
        assert processes.is_running(grandchild)
        child.kill_tree()
        await asyncio.wait_for(child.wait(), timeout=30)
        child.kill_tree()  # a second kill is harmless
        child.release()
        return child.pid, grandchild

    child_pid, grandchild_pid = asyncio.run(main())
    assert _gone_within(child_pid, 10)
    assert _gone_within(grandchild_pid, 10)


def test_closing_stdin_lets_a_child_read_end_of_file() -> None:
    async def main() -> bytes:
        child = await processes.start(
            _python("import sys; print(len(sys.stdin.read()))"),
            cwd=Path.cwd(),
            env={},
            line_limit=LIMIT,
        )
        child.stdin.write(b"abc")
        await child.stdin.drain()
        child.close_stdin()
        return await asyncio.wait_for(_output(child), timeout=30)

    assert asyncio.run(main()).strip() == b"3"


# Requirement: A child's end says whether troupe's kill ended it

KILL_STATUS = processes.KILLED_EXIT_CODE if WINDOWS else -9
"""The exit status troupe's kill gives a child: its named code on Windows, SIGKILL elsewhere."""

ENDS_ITSELF_LIKE_A_KILL = (
    f"import os; os._exit({KILL_STATUS})"
    if WINDOWS
    else "import os, signal; os.kill(os.getpid(), signal.SIGKILL)"
)


def _ended(code: str, *, kill: bool) -> tuple[int, bool]:
    """Start a child, kill it once it has said it is running (when ``kill``), and return its exit
    code and whether the seam says the kill ended it."""

    async def main() -> tuple[int, bool]:
        child = await processes.start(_python(code), cwd=Path.cwd(), env={}, line_limit=LIMIT)
        try:
            await asyncio.wait_for(child.stdout.readline(), timeout=30)
            if kill:
                child.kill_tree()
            exit_code = await asyncio.wait_for(child.wait(), timeout=30)
            return exit_code, child.ended_by_kill(exit_code)
        finally:
            child.kill_tree()
            await child.wait()
            child.release()

    return asyncio.run(main())


def test_a_running_child_troupe_killed_was_ended_by_the_kill() -> None:
    exit_code, by_kill = _ended("import time; print('up', flush=True); time.sleep(120)", kill=True)
    assert (exit_code, by_kill) == (KILL_STATUS, True)


def test_a_kill_sent_after_the_child_exited_by_itself_did_not_end_it() -> None:
    async def main() -> tuple[int, bool]:
        child = await processes.start(_python("pass"), cwd=Path.cwd(), env={}, line_limit=LIMIT)
        try:
            deadline = time.monotonic() + 30
            while child.returncode is None and time.monotonic() < deadline:
                await asyncio.sleep(0.05)
            assert child.returncode == 0
            child.kill_tree()
            exit_code = await child.wait()
            return exit_code, child.ended_by_kill(exit_code)
        finally:
            child.release()

    assert asyncio.run(main()) == (0, False)


def test_a_child_that_ends_itself_with_the_kills_status_was_not_ended_by_a_kill() -> None:
    exit_code, by_kill = _ended(f"print('up', flush=True); {ENDS_ITSELF_LIKE_A_KILL}", kill=False)
    assert (exit_code, by_kill) == (KILL_STATUS, False)


# Requirement: Child output lines are not limited to 64 KiB


def _first_line(size: int, limit: int) -> bytes:
    async def main() -> bytes:
        child = await processes.start(
            _python(f"import sys; sys.stdout.buffer.write(b'x' * {size} + b'\\n')"),
            cwd=Path.cwd(),
            env={},
            line_limit=limit,
        )
        try:
            return await processes.read_line(child.stdout, limit)
        finally:
            child.kill_tree()
            await child.wait()
            child.release()

    return asyncio.run(main())


def test_a_line_of_five_mebibytes_is_read_whole() -> None:
    line = _first_line(5 * 1024 * 1024, LIMIT)
    assert line == b"x" * (5 * 1024 * 1024) + b"\n"


def test_a_line_over_the_maximum_is_an_error_naming_the_maximum() -> None:
    with pytest.raises(LineTooLongError) as caught:
        _first_line(2 * 1024 * 1024, 1024 * 1024)
    assert caught.value.limit == 1024 * 1024
    assert "1048576" in str(caught.value)


def test_reading_at_end_of_output_returns_the_unterminated_last_line_then_nothing() -> None:
    async def main() -> list[bytes]:
        child = await processes.start(
            _python("import sys; sys.stdout.buffer.write(b'a\\nlast')"),
            cwd=Path.cwd(),
            env={},
            line_limit=LIMIT,
        )
        lines = [await processes.read_line(child.stdout, LIMIT) for _ in range(3)]
        await child.wait()
        child.release()
        return lines

    assert asyncio.run(main()) == [b"a\n", b"last", b""]


# Requirement: A command can be run to completion within a bound


def _run(code: str, **overrides: object) -> processes.Completed:
    options: dict[str, object] = {
        "cwd": Path.cwd(),
        "env": {},
        "timeout": 30.0,
        "max_output_bytes": LIMIT,
        "announce_after": 30.0,
    }
    options.update(overrides)
    return processes.run_to_completion(_python(code), **options)  # type: ignore[arg-type]


def test_a_finished_command_returns_both_outputs_and_its_exit_code() -> None:
    done = _run("import sys; sys.stdout.write('out'); sys.stderr.write('err'); sys.exit(3)")
    assert (done.returncode, done.stdout, done.stderr) == (3, b"out", b"err")


def test_input_is_given_to_the_command_on_standard_input() -> None:
    done = _run("import sys; sys.stdout.write(sys.stdin.read().upper())", input=b"abc")
    assert done.stdout == b"ABC"


GRANDPARENT_THAT_TALKS = """
import subprocess, sys, time
grandchild = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
print(grandchild.pid, flush=True)
time.sleep(120)
"""


def test_a_command_past_its_timeout_is_killed_with_its_children_and_keeps_its_output() -> None:
    with pytest.raises(ProcessTimeoutError) as caught:
        _run(GRANDPARENT_THAT_TALKS, timeout=3.0)
    error = caught.value
    assert error.timeout == 3.0
    assert error.command == sys.executable
    grandchild = int(error.stdout)
    assert _gone_within(grandchild, 10)


def test_a_command_writing_past_the_output_limit_is_killed_and_the_limit_named() -> None:
    with pytest.raises(OutputTooLargeError) as caught:
        _run(
            "import sys, time\nwhile True: sys.stdout.write('x' * 65536)", max_output_bytes=100_000
        )
    assert caught.value.limit == 100_000
    assert "100000" in str(caught.value)


def test_a_command_run_from_inside_a_running_event_loop_completes_the_same_way() -> None:
    async def inside_a_loop() -> processes.Completed:
        return _run("print('from a loop')")

    assert asyncio.run(inside_a_loop()).stdout.strip() == b"from a loop"


def test_a_long_wait_is_announced_once_with_the_command_and_the_time_waited() -> None:
    waits: list[tuple[str, float]] = []
    _run(
        "import time; time.sleep(0.5)",
        announce_after=0.1,
        on_wait=lambda command, waited: waits.append((command, waited)),
    )
    assert len(waits) == 1
    assert waits[0][0] == sys.executable
    assert waits[0][1] >= 0.1


def test_a_command_that_exits_while_its_child_holds_its_output_open_still_times_out() -> None:
    code = (
        "import subprocess, sys\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])"
    )
    with pytest.raises(ProcessTimeoutError):
        _run(code, timeout=2.0)


def test_running_a_missing_command_names_it() -> None:
    with pytest.raises(CommandNotFoundError):
        processes.run_to_completion(
            ["troupe-no-such-command"],
            cwd=Path.cwd(),
            env={},
            timeout=5,
            max_output_bytes=1024,
            announce_after=5,
        )
