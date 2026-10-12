"""Running an adapter's command: platform failures become TroupeErrors (event-store design D11)."""

import json
import os
import sys
from pathlib import Path

import pytest

from troupe.core.commands import narrow_policy, run_command
from troupe.core.errors import TroupeError
from troupe.platform.processes import EnvironmentPolicy

POLICY = EnvironmentPolicy(
    names=frozenset({"PATH", "KEEP"}), prefixes=("APP_",), never=frozenset({"APP_SECRET"})
)
PYTHON = sys.executable
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


def test_a_missing_command_is_command_not_found_naming_it(tmp_path: Path) -> None:
    with pytest.raises(TroupeError) as caught:
        run(["troupe-no-such-command-x"], tmp_path)
    assert caught.value.code == "command.not-found"
    assert "troupe-no-such-command-x" in caught.value.problem


def test_a_command_past_its_timeout_is_command_timeout_naming_it(tmp_path: Path) -> None:
    with pytest.raises(TroupeError) as caught:
        run([PYTHON, "-c", "import time; time.sleep(30)"], tmp_path, timeout=0.5)
    assert caught.value.code == "command.timeout"
    assert caught.value.details["timeout_seconds"] == 0.5
    assert "time.sleep(30)" in caught.value.details["command"]


def test_a_command_writing_past_its_limit_is_command_output_too_large_naming_it(
    tmp_path: Path,
) -> None:
    with pytest.raises(TroupeError) as caught:
        run([PYTHON, "-c", "print('x' * 100000)"], tmp_path, max_output_bytes=1000)
    assert caught.value.code == "command.output-too-large"
    assert caught.value.details["limit_bytes"] == 1000
    assert PYTHON in caught.value.details["command"]


def test_narrowing_a_policy_keeps_a_subset() -> None:
    narrowed = narrow_policy(POLICY, names={"PATH"}, never={"APP_TOKEN"})
    assert narrowed.selects("PATH")
    assert not narrowed.selects("KEEP")
    assert not narrowed.selects("APP_TOKEN")


@pytest.mark.parametrize(
    "widening",
    [
        pytest.param({"names": {"PATH", "HOME"}}, id="a name the policy doesn't select"),
        pytest.param({"prefixes": ("A",)}, id="a shorter prefix"),
    ],
)
def test_widening_a_policy_is_environment_policy_invalid(widening: dict[str, object]) -> None:
    with pytest.raises(TroupeError) as caught:
        narrow_policy(POLICY, **widening)  # type: ignore[arg-type]
    assert caught.value.code == "environment.policy-invalid"
