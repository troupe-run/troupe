"""Narrowing the git adapter's environment policy to names outside it is refused as
environment.policy-invalid (spec: vcs; event-store design D11).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_git_adapter.py."""

import pytest

from troupe.core.commands import narrow_policy
from troupe.core.errors import TroupeError
from troupe_vcs_git.defaults import GIT_ENVIRONMENT


def test_narrowing_the_git_policy_wider_is_environment_policy_invalid() -> None:
    with pytest.raises(TroupeError) as caught:
        narrow_policy(GIT_ENVIRONMENT, names={"HOME", "AWS_SECRET_ACCESS_KEY"})
    assert caught.value.code == "environment.policy-invalid"
