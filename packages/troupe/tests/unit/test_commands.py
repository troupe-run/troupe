"""Running an adapter's command: platform failures become TroupeErrors (event-store design D11).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_commands_integration.py."""

from pathlib import Path

import pytest

from commands_shared import POLICY, run
from troupe.core.commands import narrow_policy
from troupe.core.errors import TroupeError


def test_a_missing_command_is_command_not_found_naming_it(tmp_path: Path) -> None:
    with pytest.raises(TroupeError) as caught:
        run(["troupe-no-such-command-x"], tmp_path)
    assert caught.value.code == "command.not-found"
    assert "troupe-no-such-command-x" in caught.value.problem


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
