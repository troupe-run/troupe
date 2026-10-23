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

# Actor runners (spec: actor-runners; runner-contract design D8). contributing/runners.md lists
# them.

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

# Identity (spec: identity; event-store design D9). contributing/event-store.md lists it.

IDENTITY_CHAIN: tuple[str, ...] = ("env", "vcs", "os-login")
"""The identity sources asked, in order, for who is acting (#9, agreed 2026-10-12): the TROUPE_ACTOR
override, then the identity the VCS is configured with (git's user.email), then the OS login."""

# The event store (spec: event-store; event-store design D10; watch-event-segments design D5).
# contributing/event-store.md lists them.

SUBSCRIBE_POLL_SECONDS = 1.0
"""How often a subscription looks for events another process recorded, when the store can't be
told of them as they're recorded (it then says so with events.subscription-polling)."""

SUBSCRIBE_CHECK_SECONDS = 30.0
"""How often a store with subscribers looks for other processes' events itself, to catch a file
system that accepts watches but doesn't deliver them (watch-event-segments design D5)."""

SUBSCRIBE_STOP_TIMEOUT_SECONDS = 5.0
"""How long stopping a subscription waits for its thread to end before failing with
events.subscription-not-stopped (stopped-event-store design D3). The thread needs milliseconds."""

# Policy (spec: policy; perform-status-logs design D6). contributing/runs.md lists it.

ALLOW_UNENFORCED_LOCAL_STAGE = False
"""Whether a stage that can't enforce an actor's declared effects may run it anyway (decision #3,
option C). Off by default: the local stage then refuses every actor."""

# Stages (spec: stages; perform-status-logs design D5). Interim: config chooses an actor's stage.

STAGE = "local"
"""The stage an actor runs on until config says otherwise."""

# Run workspaces (spec: run-workspaces; worktree-stage design D9). contributing/runs.md lists them.

WORKSPACE = "worktree"
"""Where a run works when its actor's config doesn't say: its own git worktree at HEAD (owner,
2026-10-23). An actor sets workspace: theatre to run in place."""

WORKTREES_DIR = "worktrees"
"""The directory, under the theatre's .troupe/local/, that holds each run's worktree by run id."""

UNCOMMITTED_NOTICE_PATHS = 20
"""How many of the paths that differ from HEAD workspace.uncommitted-unseen names."""

# Where a theatre's runs are kept (perform-status-logs design D4). Interim: config names them.

VCS = "git"
"""The version-control adapter a theatre is read and recorded with."""

EVENT_STORE = "text"
"""The event store a theatre's events are kept in."""

ARTIFACT_STORE = "local"
"""The artifact store a theatre's transcripts and large payloads are kept in."""

# Reading runs back (spec: runs; perform-status-logs design D13; watch-event-segments design D6).
# contributing/runs.md lists them.

STATUS_RUNS_LIMIT = 20
"""How many runs status lists, newest first, when the request doesn't say."""

LOGS_LEASE_CHECK_SECONDS = 1.0
"""How often logs --follow checks that the run it follows is still running, so a perform that dies
without recording an end is noticed though it wrote nothing. One check is one try of a lock. New
events wake following through the store's subscription, never a timer (watch-event-segments D6)."""
