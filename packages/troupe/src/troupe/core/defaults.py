"""Default values for troupe's limits, in one named place (design D6).

Every timeout, size or other limit troupe uses has its default here. Callers can override each one;
the ``settings`` capability will later let configuration override them too, bounded by policy.
"""

from troupe.platform.processes import EnvironmentPolicy

LOCK_TIMEOUT_SECONDS = 30.0
"""How long to wait for another process's lock before giving up."""

LOCK_ANNOUNCE_AFTER_SECONDS = 1.0
"""How long a lock wait lasts before troupe says what it is waiting for."""

REPLACE_TIMEOUT_SECONDS = 10.0
"""How long to keep retrying a file replacement that another program is blocking (Windows)."""

REPLACE_ANNOUNCE_AFTER_SECONDS = 1.0
"""How long a blocked replacement lasts before troupe says which file it is waiting for."""

# Actor runners (spec: actor-runners; runner-contract design D8). docs/runners.md lists them.

RUNNER_START_TIMEOUT_SECONDS = 30.0
"""How long a runner has to start and answer the handshake."""

RUN_TIMEOUT_SECONDS = 3600.0
"""How long a run may go on before it is cancelled as timed out."""

RUNNER_CANCEL_GRACE_SECONDS = 10.0
"""How long a runner has to exit after run/cancel or shutdown before its process tree is killed."""

RUN_SILENCE_ANNOUNCE_SECONDS = 30.0
"""How long a run may go without an event before troupe says it has been silent."""

RUNNER_MAX_MESSAGE_BYTES = 64 * 1024 * 1024
"""The longest single protocol message (one line) troupe accepts from a runner."""

RUN_EVENT_MAX_BYTES = 64 * 1024
"""The largest run event kept inline; a larger one is stored as an artifact and referenced."""

RUN_TRANSCRIPT_MAX_BYTES = 1024 * 1024 * 1024
"""The largest transcript a run may produce before it is cancelled."""

RUNNER_STDERR_MAX_BYTES = 1024 * 1024
"""How much of a runner's standard error is kept: the first and last halves of this, at most."""

RUNNER_FAIL_FAST_ON_AUTH_RETRY = True
"""Whether a retry because authentication failed cancels the run at once."""

RUNNER_ENVIRONMENT = EnvironmentPolicy()
"""What a runner receives from troupe's environment: nothing. It gets only the variables its caller
names, plus the platform minimum (design D6)."""
