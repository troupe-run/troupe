"""Tests for the limits a run is held to (spec: actor-runners)."""

from dataclasses import replace

import pytest

from troupe.core import defaults
from troupe.core.runners.limits import RunLimits


def test_every_limit_defaults_to_its_named_setting() -> None:
    assert RunLimits().to_data() == {
        "start_timeout": defaults.RUNNER_START_TIMEOUT_SECONDS,
        "run_timeout": defaults.RUN_TIMEOUT_SECONDS,
        "cancel_grace": defaults.RUNNER_CANCEL_GRACE_SECONDS,
        "silence_announce": defaults.RUN_SILENCE_ANNOUNCE_SECONDS,
        "max_message_bytes": defaults.RUNNER_MAX_MESSAGE_BYTES,
        "event_max_bytes": defaults.RUN_EVENT_MAX_BYTES,
        "transcript_max_bytes": defaults.RUN_TRANSCRIPT_MAX_BYTES,
        "stderr_max_bytes": defaults.RUNNER_STDERR_MAX_BYTES,
        "fail_fast_on_auth_retry": defaults.RUNNER_FAIL_FAST_ON_AUTH_RETRY,
    }


def test_a_caller_can_override_one_limit_and_keep_the_other_defaults() -> None:
    limits = RunLimits(run_timeout=5.0)
    assert limits.run_timeout == 5.0
    assert limits.cancel_grace == defaults.RUNNER_CANCEL_GRACE_SECONDS


@pytest.mark.parametrize("field", ["run_timeout", "cancel_grace", "event_max_bytes"])
def test_a_limit_that_is_not_positive_is_refused(field: str) -> None:
    overrides: dict[str, object] = {field: 0}
    with pytest.raises(ValueError, match=f"run limit {field} must be positive"):
        replace(RunLimits(), **overrides)  # type: ignore[arg-type]


def test_the_message_limit_cannot_be_smaller_than_the_event_limit() -> None:
    with pytest.raises(ValueError, match="at least event_max_bytes"):
        RunLimits(max_message_bytes=1024, event_max_bytes=2048)
