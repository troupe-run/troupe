"""Helpers that test_perform_runtime.py shares with other test modules."""

import importlib
from pathlib import Path
from typing import Any

import pytest

from runtesting import Harness, theatre


def _harness(tmp_path: Path, **env: str) -> Harness:
    harness = Harness(theatre(tmp_path))
    harness.env = {**harness.env, **env}
    return harness


def _runner_commands(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    perform_module = importlib.import_module("troupe.core.runs.perform")
    seen: list[Any] = []
    real = perform_module.run_actor

    async def capture(command: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        seen.append((command, args))
        return await real(command, *args, **kwargs)

    monkeypatch.setattr(perform_module, "run_actor", capture)
    return seen
