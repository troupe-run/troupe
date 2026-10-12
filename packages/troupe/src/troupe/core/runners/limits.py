"""The limits a run is held to (spec: actor-runners; runner-contract design D8).

Each defaults to its named setting in troupe.core.defaults and can be overridden per run.
"""

from dataclasses import dataclass, fields

from troupe.core import defaults


@dataclass(frozen=True)
class RunLimits:
    start_timeout: float = defaults.RUNNER_START_TIMEOUT_SECONDS
    run_timeout: float = defaults.RUN_TIMEOUT_SECONDS
    cancel_grace: float = defaults.RUNNER_CANCEL_GRACE_SECONDS
    silence_announce: float = defaults.RUN_SILENCE_ANNOUNCE_SECONDS
    max_message_bytes: int = defaults.RUNNER_MAX_MESSAGE_BYTES
    event_max_bytes: int = defaults.RUN_EVENT_MAX_BYTES
    transcript_max_bytes: int = defaults.RUN_TRANSCRIPT_MAX_BYTES
    stderr_max_bytes: int = defaults.RUNNER_STDERR_MAX_BYTES
    fail_fast_on_auth_retry: bool = defaults.RUNNER_FAIL_FAST_ON_AUTH_RETRY

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if isinstance(value, bool):
                continue
            if value <= 0:
                msg = f"run limit {field.name} must be positive, not {value!r}"
                raise ValueError(msg)
        if self.max_message_bytes < self.event_max_bytes:
            msg = "run limit max_message_bytes must be at least event_max_bytes"
            raise ValueError(msg)

    def to_data(self) -> dict[str, float | int | bool]:
        """The limits in effect, by name, for recording with a run's outcome."""
        return {field.name: getattr(self, field.name) for field in fields(self)}
