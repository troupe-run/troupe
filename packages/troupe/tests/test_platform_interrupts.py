"""Ctrl-C is caught the same way on every platform (perform-status-logs design D10)."""

import queue
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from interrupt_child import BUSY_INTERRUPTS, PADDING

CHILD = Path(__file__).with_name("interrupt_child.py")


def _interrupt(process: subprocess.Popen[str]) -> None:
    if sys.platform == "win32":
        # A process in its own console process group gets Ctrl-Break, never Ctrl-C.
        process.send_signal(signal.CTRL_BREAK_EVENT)
    else:
        process.send_signal(signal.SIGINT)


def test_each_interrupt_calls_back_instead_of_stopping_and_the_old_handler_returns() -> None:
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP
    process = subprocess.Popen(
        [sys.executable, str(CHILD)],
        stdout=subprocess.PIPE,
        text=True,
        creationflags=flags,
    )
    assert process.stdout is not None
    assert process.stdout.readline().strip() == "READY"
    _interrupt(process)
    assert process.stdout.readline().strip() == "INTERRUPTED 1"
    time.sleep(0.1)
    _interrupt(process)
    assert process.stdout.readline().strip() == "INTERRUPTED 2"
    assert process.stdout.readline().strip() == "RESTORED True"
    assert process.wait(timeout=30) == 0


@pytest.mark.skipif(sys.platform != "win32", reason="Ctrl-C as a console event is Windows' own")
def test_a_real_ctrl_c_on_windows_calls_back_too() -> None:
    # Ctrl-C is disabled for a process started in a new process group, which is why the test above
    # sends Ctrl-Break. A person's Ctrl-C reaches troupe in the console's foreground group instead,
    # so here the child gets a console of its own and sends Ctrl-C to it.
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_CONSOLE
    process = subprocess.Popen(
        [sys.executable, str(CHILD), "self"],
        stdout=subprocess.PIPE,
        text=True,
        creationflags=flags,
    )
    assert process.stdout is not None
    assert process.stdout.readline().strip() == "READY"
    assert process.stdout.readline().strip() == "INTERRUPTED 1"
    assert process.stdout.readline().strip() == "INTERRUPTED 2"
    assert process.stdout.readline().strip() == "RESTORED True"
    assert process.wait(timeout=30) == 0


def test_interrupts_arriving_while_the_child_is_writing_do_not_kill_it() -> None:
    # The child writes all the time, so every interrupt arrives while it's writing. One that lands
    # inside a write runs the handler there, and a callback that wrote too would re-enter the stream
    # and kill it (#96). Whether a given interrupt lands inside a write is chance, not arranged: on
    # macOS, a child whose callback printed died in 10 of 10 runs of this shape; one that only
    # counts, in none.
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP
    process = subprocess.Popen(
        [sys.executable, str(CHILD), "busy"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=flags,
    )
    stdout, stderr = process.stdout, process.stderr
    assert stdout is not None
    assert stderr is not None
    lines: queue.Queue[str | None] = queue.Queue()

    def read() -> None:
        for line in stdout:
            lines.put(line.strip())
        lines.put(None)

    # Read on a thread, so the child's padding never fills the pipe and every read has a deadline.
    threading.Thread(target=read, daemon=True).start()
    deadline = time.monotonic() + 30
    seen: list[str] = []

    def expect(wanted: str) -> None:
        while True:
            try:
                line = lines.get(timeout=max(deadline - time.monotonic(), 0))
            except queue.Empty:
                process.kill()
                pytest.fail(f"no {wanted!r} within 30 s; read {seen}, stderr: {stderr.read()}")
            if line == PADDING:
                continue
            if line is None:
                process.wait(timeout=30)
                pytest.fail(
                    f"the child exited before {wanted!r}; read {seen}, stderr: {stderr.read()}"
                )
            seen.append(line)
            assert line == wanted, f"read {seen}"
            return

    expect("READY")
    for n in range(1, BUSY_INTERRUPTS + 1):
        # Each once the one before is reported, so none is pending when the old handler comes back.
        _interrupt(process)
        expect(f"INTERRUPTED {n}")
    expect("RESTORED True")
    assert process.wait(timeout=30) == 0
    assert stderr.read() == ""
