"""Running an adapter's command: platform failures become TroupeErrors (event-store design D11).

Its tests that stay in their own process are in unit/test_commands.py."""

import json
import sys
from pathlib import Path

import pytest

from commands_shared import PARENT, POLICY, run, source
from troupe.core.commands import run_command
from troupe.core.errors import TroupeError

PYTHON = sys.executable


def test_the_command_sees_only_what_the_policy_selects(tmp_path: Path) -> None:
    code = "import json, os; print(json.dumps(sorted(os.environ)))"
    completed = run_command(
        [PYTHON, "-c", code],
        cwd=tmp_path,
        policy=POLICY,
        timeout=10.0,
        max_output_bytes=1_000_000,
        announce_after=5.0,
        source=source(**PARENT),
    )
    seen = set(json.loads(completed.stdout))
    assert {"KEEP", "APP_NAME", "PATH"} <= seen
    assert "DROP" not in seen
    assert "APP_SECRET" not in seen


def test_a_command_past_its_timeout_is_command_timeout_naming_it(tmp_path: Path) -> None:
    with pytest.raises(TroupeError) as caught:
        run([PYTHON, "-c", "import time; time.sleep(30)"], tmp_path, timeout=0.5)
    assert caught.value.code == "command.timeout"
    assert caught.value.details["timeoutSeconds"] == 0.5
    assert "time.sleep(30)" in caught.value.details["command"]


def test_a_command_writing_past_its_limit_is_command_output_too_large_naming_it(
    tmp_path: Path,
) -> None:
    with pytest.raises(TroupeError) as caught:
        run([PYTHON, "-c", "print('x' * 100000)"], tmp_path, max_output_bytes=1000)
    assert caught.value.code == "command.output-too-large"
    assert caught.value.details["limitBytes"] == 1000
    assert PYTHON in caught.value.details["command"]
