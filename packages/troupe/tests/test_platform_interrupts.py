"""Ctrl-C is caught the same way on every platform (perform-status-logs design D10)."""

import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

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
