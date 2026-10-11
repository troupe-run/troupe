"""Run every quality gate, in order, stopping at the first failure.

Usage: uv run scripts/check.py

The same script runs locally and in CI on Linux, macOS and Windows, so the two can't
diverge. It is Python rather than shell for that reason.
"""

import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIN = Path(sys.executable).parent


def tool(name: str) -> str:
    """Find a console script installed in the same environment as this interpreter."""
    found = shutil.which(name, path=str(BIN))
    if found is None:
        sys.exit(f"check: {name} is not installed in {BIN}. Fix: run `uv sync`.")
    return found


GATES: list[tuple[str, list[str]]] = [
    ("ruff lint", [tool("ruff"), "check", "."]),
    ("ruff format", [tool("ruff"), "format", "--check", "."]),
    ("mypy --strict", [tool("mypy")]),
    ("import contracts", [tool("lint-imports")]),
    ("tests", [tool("pytest")]),
]


def main() -> int:
    for label, command in GATES:
        print(f"==> {label}", flush=True)
        started = time.monotonic()
        result = subprocess.run(command, cwd=ROOT, check=False)
        elapsed = time.monotonic() - started
        if result.returncode != 0:
            code = result.returncode
            print(f"check: {label} failed (exit {code}) after {elapsed:.1f}s", flush=True)
            return result.returncode
        print(f"    {label} passed in {elapsed:.1f}s", flush=True)
    print("check: all gates passed", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
