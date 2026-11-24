"""perform's refusal of an Anthropic runtime whose endpoint from config ends in /v1 names the base
to use and the config path the endpoint came from (spec: runtimes, "An Anthropic actor on an
endpoint ending in /v1"; runtimes design D5, D6, D8).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_perform_runtime.py."""

import pytest

from troupe.core import runtimes
from troupe.core.errors import TroupeError


def test_the_unfit_refusal_names_the_base_for_an_endpoint_from_config_ending_in_v1() -> None:
    # Spec: runtimes, "An Anthropic actor on an endpoint ending in /v1". Config refuses such a
    # runtime when it's set, so perform meets one only from a merge that brought it in; the shared
    # refusal names the base to use, and where the endpoint came from (owner, 2026-11-14).
    config = {"runtimes": {"claude-v1": {"endpoint": "https://api.anthropic.com/v1"}}}
    resolved = runtimes.resolve("claude-v1", config, {})
    with pytest.raises(TroupeError) as raised:
        runtimes.refuse_unfit(resolved, "anthropic", "tester", config, {})
    error = raised.value
    assert error.code == "runtime.unfit"
    assert error.details["reasons"] == ["endpoint-version"]
    assert error.details["from"] == {"endpoint": "runtimes.claude-v1.endpoint"}
    assert "already ends in /v1 (use https://api.anthropic.com)" in error.problem
    assert "runtimes.claude-v1.endpoint" in error.fix
