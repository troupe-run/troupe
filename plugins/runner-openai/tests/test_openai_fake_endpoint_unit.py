"""The fake endpoint's pause, timed on its own with no request served, lasts its length even by a
monotonic clock as coarse as Windows' on Python 3.12 (openai-style-runner design D13). The
runner's own tests rely on it.

Its tests that start a process, open a socket or use a git theatre are in
integration/test_openai_fake_endpoint.py."""

import math
import time

import pytest

import fake_endpoint

WINDOWS_312_TICK = 0.015625
"""time.monotonic's resolution on Windows with Python 3.12 (GetTickCount64), where #352 failed."""


def test_a_pause_lasts_its_length_by_a_monotonic_clock_as_coarse_as_windows_on_3_12(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A 0.3 s sleep read by a clock that ticks every 15.625 ms comes out as 19 ticks (0.297 s) for
    # most start times: the failure #352 saw. The fake's pause must last its length by that clock.
    real = time.monotonic
    monkeypatch.setattr(
        time, "monotonic", lambda: math.floor(real() / WINDOWS_312_TICK) * WINDOWS_312_TICK
    )
    for _ in range(5):  # different start times within a tick
        started = time.monotonic()
        fake_endpoint.pause(0.3)  # timed alone: the HTTP around it would hide a short pause
        assert time.monotonic() - started >= 0.3
