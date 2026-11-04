"""The Claude Code runner's stand-in claude, for core's tests (claude-code-runner design D12).

The stand-in lives with the plugin's tests (plugins/runner-claude-code/tests/fake_claude.py) and
uses only the standard library, so it's loaded here by path: core's tests run the real runner
with it first on the runner's PATH, through the host, the conformance suite and perform.
"""

import importlib.util
import json
import time
from pathlib import Path
from types import ModuleType
from typing import Any

PLUGIN = Path(__file__).resolve().parents[3] / "plugins" / "runner-claude-code"
FIXTURES = PLUGIN / "fixtures" / "claude-code"
NAMES = sorted(path.name for path in FIXTURES.iterdir() if path.is_dir())
TIMEOUT = 30.0


def _fake() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "claude_code_fake_claude", PLUGIN / "tests" / "fake_claude.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("the stand-in claude can't be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def install(bin_dir: Path, **settings: str) -> Path:
    """A ``claude`` in ``bin_dir`` that runs the stand-in with ``settings`` (each a
    ``FAKE_CLAUDE_<NAME>`` variable, given here by lower-case name)."""
    shim: Path = _fake().install(
        bin_dir, {f"FAKE_CLAUDE_{name.upper()}": value for name, value in settings.items()}
    )
    return shim


def fixture(name: str) -> str:
    return str(FIXTURES / name / "recording.jsonl")


def expected(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(
        (FIXTURES / name / "expected.json").read_text(encoding="utf-8")
    )
    return loaded


def native_lines(name: str) -> list[str]:
    text = (FIXTURES / name / "recording.jsonl").read_text(encoding="utf-8")
    entries = [json.loads(line) for line in text.splitlines()]
    return [entry["transcript"] for entry in entries if "transcript" in entry]


def wait_for_record(path: Path, key: str, timeout: float = TIMEOUT) -> dict[str, Any]:
    """The stand-in's record at ``path`` once it holds ``key``. Fails after ``timeout``."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            record: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        except OSError:
            record = {}
        if key in record:
            return record
        time.sleep(0.02)
    raise AssertionError(f"the stand-in claude never recorded {key!r} in {path}")
