"""The stand-in claude writes each fixture's native lines byte for byte (task 7.1), and records
itself in a ledger while it runs (reap-fake-claude design D2)."""

import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

import fake_claude
from claude_harness import FIXTURES, recording, wait_for_record
from fake_claude import (
    described,
    forget,
    install,
    ledger_entries,
    still_running,
    stop,
)

NAMES = sorted(path.name for path in FIXTURES.iterdir() if path.is_dir())


@pytest.mark.parametrize("name", NAMES)
def test_the_stand_in_writes_a_fixtures_native_lines_byte_for_byte(
    name: str, tmp_path: Path
) -> None:
    shim = install(tmp_path / "bin")
    record = tmp_path / "record.json"
    env = {
        **os.environ,
        "FAKE_CLAUDE_FIXTURE": str(FIXTURES / name / "recording.jsonl"),
        "FAKE_CLAUDE_RECORD": str(record),
    }
    done = subprocess.run(
        [str(shim), "-p", "--setting-sources", ""],
        input=b"say hi",
        capture_output=True,
        env=env,
        cwd=tmp_path,
        check=False,
        timeout=60,
    )
    native = [line["transcript"] for line in recording(name) if "transcript" in line]
    assert done.stdout == b"".join(line.encode("utf-8") + b"\n" for line in native)
    seen = json.loads(record.read_text(encoding="utf-8"))
    assert seen["argv"] == ["-p", "--setting-sources", ""]
    assert seen["stdin"] == "say hi"
    assert done.returncode == 0


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no SIGTERM to send")
def test_the_stand_in_exits_143_on_sigterm_as_claude_code_does(tmp_path: Path) -> None:
    import signal

    shim = install(tmp_path / "bin")
    record = tmp_path / "record.json"
    env = {**os.environ, "FAKE_CLAUDE_HANG": "1", "FAKE_CLAUDE_RECORD": str(record)}
    process = subprocess.Popen([str(shim)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env)
    assert process.stdin is not None
    process.stdin.close()
    assert wait_for_record(record, "argv")["pid"] == process.pid
    process.send_signal(signal.SIGTERM)
    assert process.wait(timeout=30) == 143


# The ledger (reap-fake-claude design D2)

LEDGER_WAIT_SECONDS = 30.0


def _until(condition: Callable[[], bool], what: str) -> None:
    deadline = time.monotonic() + LEDGER_WAIT_SECONDS
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError(f"{what} within {LEDGER_WAIT_SECONDS:g}s")
        time.sleep(0.02)


def _hanging(shim: Path, env: dict[str, str]) -> subprocess.Popen[bytes]:
    process = subprocess.Popen(
        [str(shim)], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, env=env
    )
    assert process.stdin is not None
    process.stdin.close()
    return process


def test_a_hanging_stand_in_holds_its_ledger_lock_until_it_is_killed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    monkeypatch.setenv(fake_claude.LEDGER, str(ledger))
    shim = install(tmp_path / "bin")
    process = _hanging(shim, {**os.environ, "FAKE_CLAUDE_HANG": "1"})
    try:
        _until(lambda: len(ledger_entries(ledger)) == 1, "the stand-in never recorded itself")
        (pid,) = ledger_entries(ledger)
        _until(lambda: described(ledger, pid) is not None, "the stand-in never described itself")
        assert described(ledger, pid) == {"pid": pid, "cwd": os.getcwd(), "argv": []}
        assert still_running(ledger, pid)
        stop(pid)
        _until(
            lambda: not still_running(ledger, pid), "the killed stand-in's lock was never released"
        )
    finally:
        process.kill()
        process.wait(timeout=LEDGER_WAIT_SECONDS)


def test_the_shim_carries_the_ledger_to_a_stand_in_whose_environment_leaves_it_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    monkeypatch.setenv(fake_claude.LEDGER, str(ledger))
    shim = install(tmp_path / "bin")
    env = {name: value for name, value in os.environ.items() if name != fake_claude.LEDGER}
    done = subprocess.run(
        [str(shim)], input=b"", env=env, capture_output=True, timeout=60, check=False
    )
    assert done.returncode == 0
    (pid,) = ledger_entries(ledger)
    assert not still_running(ledger, pid)


def test_with_no_ledger_set_the_shim_names_none_and_the_stand_in_still_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(fake_claude.LEDGER, raising=False)
    shim = install(tmp_path / "bin")
    assert fake_claude.LEDGER not in shim.read_text(encoding="utf-8")
    env = {name: value for name, value in os.environ.items() if name != fake_claude.LEDGER}
    done = subprocess.run(
        [str(shim)], input=b"", env=env, capture_output=True, timeout=60, check=False
    )
    assert done.returncode == 0


def test_an_entry_whose_pid_another_process_now_has_reads_as_ended_and_it_isnt_signalled(
    tmp_path: Path,
) -> None:
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        ledger = tmp_path / "ledger"
        ledger.mkdir()
        (ledger / f"{other.pid}.lock").touch()  # a stand-in that ended, its pid since reused
        assert ledger_entries(ledger) == {other.pid}
        assert not still_running(ledger, other.pid)
        assert other.poll() is None
    finally:
        other.kill()
        other.wait(timeout=LEDGER_WAIT_SECONDS)


def test_a_forgotten_entry_is_no_longer_listed_and_leaves_no_files(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    (ledger / "4242.lock").touch()
    (ledger / "4242.json").write_text("{}", encoding="utf-8")
    assert ledger_entries(ledger) == {4242}
    forget(ledger, 4242)
    assert ledger_entries(ledger) == set()
    assert list(ledger.iterdir()) == []
