"""Catching Ctrl-C (spec: cli; perform-status-logs design D10).

One mechanism on every platform: ``signal.signal`` for SIGINT, and on Windows also SIGBREAK, which
is what Ctrl-Break sends (and the only console event a process in its own process group receives).
The handlers run in the main thread, between bytecodes, so the callback must be quick and safe to
call there: it asks for something to happen, it doesn't do it. The previous handlers come back when
the block ends, however it ends.
"""

import signal
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from types import FrameType

if sys.platform == "win32":
    INTERRUPTS: tuple[signal.Signals, ...] = (signal.SIGINT, signal.SIGBREAK)
else:
    INTERRUPTS = (signal.SIGINT,)
"""The signals a person's Ctrl-C (or Ctrl-Break, on Windows) arrives as."""


@contextmanager
def on_interrupt(callback: Callable[[], None]) -> Iterator[None]:
    """Call ``callback`` on each Ctrl-C while the block runs, instead of raising
    KeyboardInterrupt. Must be entered in the main thread."""

    def handler(signum: int, frame: FrameType | None) -> None:
        del signum, frame
        callback()

    previous = {each: signal.getsignal(each) for each in INTERRUPTS}
    try:
        for each in INTERRUPTS:
            signal.signal(each, handler)
        yield
    finally:
        for each, old in previous.items():
            signal.signal(each, old)
