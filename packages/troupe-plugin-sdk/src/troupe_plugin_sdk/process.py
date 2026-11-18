"""Ending a runner's process (spec: plugin-sdk; quality-gates design D6).

A runner ends with ``os._exit``, not ``sys.exit``: a reader thread may still be blocked on standard
input or a pipe, and ``os._exit`` ends the process without waiting for it. That also skips the
``atexit`` hook where coverage.py saves what it measured, so a runner run under coverage, as CI's
coverage leg runs every runner the tests start, would report none of its code as run.

``exit_now`` is ``os._exit``, except that when coverage.py is already measuring this process it
first stops and saves it. It never imports coverage.py: a runner outside a coverage run behaves
exactly as with ``os._exit`` (owner, 2026-11-18).
"""

import contextlib
import os
import sys
from typing import NoReturn


def _running_coverage() -> object | None:
    """coverage.py's measurement of this process, if coverage.py is loaded and measuring."""
    coverage = sys.modules.get("coverage")
    current = getattr(getattr(coverage, "Coverage", None), "current", None)
    return current() if callable(current) else None


def exit_now(code: int) -> NoReturn:
    """End the process at once with ``code``, as ``os._exit`` does, after letting a running
    coverage.py save its data. Saving never stops the exit."""
    running = _running_coverage()
    if running is not None:
        with contextlib.suppress(Exception):
            running.stop()  # type: ignore[attr-defined]
            running.save()  # type: ignore[attr-defined]
    os._exit(code)
