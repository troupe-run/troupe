"""What test_runner_warm_up.py and test_runner_warm_up_unit.py share."""

import dataclasses
import sys

import pytest

from troupe.core import interim


def _runner(monkeypatch: pytest.MonkeyPatch, script: str, warm: tuple[str, ...] = ("go",)) -> None:
    """Make the mistralrs runner a script that, given ``warm``, runs ``script``."""
    entry = dataclasses.replace(
        interim.RUNNERS["mistralrs"], command=(sys.executable, "-c", script), warm_up=warm
    )
    monkeypatch.setitem(interim.RUNNERS, "mistralrs", entry)
