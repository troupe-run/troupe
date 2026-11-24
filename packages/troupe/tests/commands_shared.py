"""What test_commands.py and test_commands_integration.py share."""

import os
import sys
from pathlib import Path

from troupe.core.commands import run_command
from troupe.platform.processes import EnvironmentPolicy

POLICY = EnvironmentPolicy(
    names=frozenset({"PATH", "KEEP"}), prefixes=("APP_",), never=frozenset({"APP_SECRET"})
)
PARENT = {"KEEP": "yes", "DROP": "no", "APP_NAME": "troupe", "APP_SECRET": "not-a-real-one"}


def source(**extra: str) -> dict[str, str]:
    base = {"PATH": os.environ["PATH"]}
    if sys.platform == "win32":
        base["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    return base | extra


def run(argv: list[str], tmp_path: Path, **overrides: float | int) -> object:
    return run_command(
        argv,
        cwd=tmp_path,
        policy=POLICY,
        timeout=float(overrides.get("timeout", 10.0)),
        max_output_bytes=int(overrides.get("max_output_bytes", 1_000_000)),
        announce_after=float(overrides.get("announce_after", 5.0)),
        source=source(**PARENT),
    )
