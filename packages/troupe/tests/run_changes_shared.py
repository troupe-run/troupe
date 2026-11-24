"""Helpers that test_run_changes.py shares with other test modules."""

import asyncio
from typing import Any

from runtesting import Harness
from troupe.core.client import messages as m
from troupe.core.runs.changes import discard


def call_discard(made: Harness, run: str, **fields: Any) -> m.DiscardResult:  # noqa: ANN401
    return asyncio.run(
        discard(
            m.DiscardRequest.from_data({"run": run, **fields}),
            made.session(),
            made.send,
            backends=made.backends(),
        )
    )
