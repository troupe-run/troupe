# Design

## Context

See proposal.md for why. `troupe.core.config.syncing` and `troupe.core.runs.changes` work on an `EventStore`, whose
version control is git in every integration test. A unit test may not start a process or use a git theatre (the
kinds detector, `scripts/kinds_pytest.py`). The `files` version control (`troupe-vcs-files`) needs neither, and
`storetesting.files_service` already builds a real event store over it for unit tests
(`test_run_changes_recording.py`). It refuses what only git can do: merge sides are empty, and `check_apply`,
`apply` and `remove_worktree` raise.

`troupe.core.runners.conformance` starts the runner under test with `troupe.platform.processes.start` for each of
its eight checks, kills each child's tree in a `finally`, and ends with `run_actor`, which starts it again. That is
process management, which the owner's rule keeps off the host's mutation runs (orchestrator, 2026-11-27).

## Goals / Non-Goals

**Goals:**

- Every branch of the three modules runs in a unit test, in-process, through the module's own entry points
  (`sync_config` and `file_notices`; `check_runner`; `diff`, `accept` and `discard`).
- A test fails when what a sync records or reports, which conformance check fails and its problem, or what
  settling a run refuses, records or returns changes.

**Non-Goals:**

- Testing the sweep, the write-back, the projection's planning, the run host or the git adapter: their own tests do.
- Starting a process, sending a signal or using a git theatre in a unit test.
- `core/runs/perform.py` and the CLI's waiting hint (troupe#536 is changing them).

## Decisions

### D1. A real event store over the `files` version control

syncing's and changes' tests use `files_service(tmp_path)`: the real text store, the real recorder and the real
config stream, so every event a test records is validated and read back as troupe does. Config is put in place the
way a person does it, by writing files under `.troupe/` and syncing, or with a sync's own operations, so the
config's state is never a hand-written shape.

### D2. Stand in only for what git alone can do

Where a branch needs git (merge sides of a file git merged, checking and applying a diff, removing a worktree), a
small subclass of the `files` version control overrides that one method, recording calls and returning protocol
types (`MergeSides`, `Applicability`). Conflicting config heads, which only a merge of two clones' event logs makes,
come from writing a second head's events into the theatre's log with the store itself, if the store allows it in
one process; otherwise a test replaces `syncing.read` with the `Merged` the real reader returns for two heads, built
by `troupe.core.config.merge`. Whichever is used is named in the test.

### D3. A conformance runner in-process

`check_runner`'s tests replace `troupe.platform.processes.start` with a function returning a stand-in child: its
`stdin` feeds a scripted runner coroutine that answers with real `troupe_plugin_sdk.runner` messages on an
`asyncio.StreamReader` given as `stdout`; `wait`, `close_stdin`, `kill_tree` and `release` record their calls.
`run_actor` is replaced by a stand-in returning an `ActorOutcome` (succeeded, or failed with an error). Each test
picks the runner's misbehaviour (an unoffered version, extra capabilities, a second initialize answered, a wrong
id, a malformed line, ended output, never exiting) and asserts the check's name, verdict and problem, masked. No
process starts and no signal is sent; the kinds detector fails the test if one did.

### D4. Tests by module, one commit each

Order: syncing (#527), conformance (#528), changes (#529), as the issue asks. Each module's tests are new files
(`test_config_syncing_unit.py`, `test_runner_conformance_unit.py`, `test_run_changes_unit.py`, split further if a
file nears the size gate's warning). What two files share goes in a helper beside the suites, as the kinds detector
asks.

### D5. Measured locally for syncing and changes, not for conformance

With the local mutation slot granted each time: mutmut 3.8.1 in a throwaway clone with this branch's tests, the
unit tests only, scoped to one module, at most 2 children, `scripts/mutation.json`'s settings, with the clone's copy
setting `mutant_memory_mb` to null (macOS refuses `RLIMIT_AS`, which would count every mutant caught). The
repository's copy is unchanged. `troupe.core.runs.changes` was checked through its imports before mutating: its own
code starts nothing and sends no signal; the lease probe it can reach (`queries._holder_has_ended`, `kill(pid, 0)`)
runs only for a run whose lease lock is held, which no test sets up. conformance is not mutated on the host: it's
measured in a throwaway container (the clone only, unit tests only) or left to CI's mutation report.

## Risks / Trade-offs

- A stand-in that drifts from git's behaviour could pass a test git would fail → stand-ins return the protocol's own
  types, and the integration tests keep running the real thing.
- CI's mutation-pr mutates only changed source files, so for a tests-only PR the local scores (and conformance's
  container or nightly score) are recorded in the PR body, and the next nightly run confirms them.
