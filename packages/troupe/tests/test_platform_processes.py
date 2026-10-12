"""Tests for child processes (spec: platform)."""

import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

from troupe.platform import processes
from troupe.platform.errors import CommandNotFoundError, LineTooLongError

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


# Requirement: Child output lines are not limited to 64 KiB


def _first_line(size: int, limit: int) -> bytes:
    async def main() -> bytes:
        child = await processes.start(
            _python(f"import sys; sys.stdout.write('x' * {size} + '\\n')"),
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
            _python("import sys; sys.stdout.write('a\\nlast')"),
            cwd=Path.cwd(),
            env={},
            line_limit=LIMIT,
        )
        lines = [await processes.read_line(child.stdout, LIMIT) for _ in range(3)]
        await child.wait()
        child.release()
        return lines

    assert asyncio.run(main()) == [b"a\n", b"last", b""]
