# Proposal: a failed run records what the audit of its changes found

Issue: troupe-run/troupe#272.

## Why

#241 (`declared-effects`) audits a run's changes against its actor's declared effects, but the run host only runs
the audit when the runner's result is `ok`, because a run that already failed has its one outcome error. So a run
that ended `failed` with an error result, `timed-out`, `cancelled` or `crashed` records nothing about whether it also
changed files outside its declaration. Its worktree is kept and `troupe diff` shows the changes, but nothing says which
ones broke the declaration, so a reviewer deciding whether to accept or discard it has to work that out by hand.

## What Changes

- The run host runs the audit for **every run whose runner started**, whatever its outcome, once the runner has ended.
  When the result is `ok` the audit stays part of the effect check, exactly as now. Otherwise it doesn't change the
  outcome or its error: a failed run keeps the one error it failed with.
- The run's end records the audit's findings, as `outcome.audit` in `Run.Ended`: the list of changes outside the
  declaration (each with its path, what happened to it, the effect it needed and, for a move, where it went), empty
  when every change was declared, or the error that kept the audit from reading the workspace. It's absent when the
  runner never started, and in an end recorded before this change.
- A failure to read the workspace for the audit no longer escapes the run host. It's recorded as the audit's error,
  and for an `ok` result it fails the effect check with `effects.audit-failed`, rather than leaving the run without an
  end (shown as interrupted).
- The run summary that `status`, `logs` and `perform` return carries the audit, and `troupe status <run>` and
  `troupe logs <run>` show it beside the outcome: each change outside the declaration, "every change was declared"
  when there were none, or that the audit couldn't run and why.
- The effect check's expected files are still checked only for an `ok` result: a run that failed isn't expected to
  have produced its files.
- The protocol changes in place (version 0): `run-ended.schema.json` gains `outcome.audit`, and the client run summary
  gains `audit`.

Two parts go beyond what #272 asks for, and the owner agreed on 2026-11-04 that both belong in this change:

- **A failure to read the workspace is caught for every outcome**, including `ok`, which then fails with
  `effects.audit-failed`. Once the audit runs after every run, catching it only for failed runs would leave two ways
  of handling the same error.
- **The audit is recorded for a succeeded run too** (always empty). That keeps one rule, "present exactly when the
  runner started", so a missing audit means only an end recorded before this change or a runner that never started.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `effects`: "Every run's changes are audited against its declaration" says the audit runs whatever the outcome, and
  what a failed run does with its findings; a new requirement for a read failure.
- `actor-runners`: success's effect check takes the audit's verdict; the audit's findings are part of the outcome.
- `runs`: the run's end records `outcome.audit`, and when it's left out.
- `client-protocol`: a run summary carries `audit` exactly when its end recorded one.
- `cli`: `status <run>` and `logs <run>` show the audit's findings beside the outcome.

## Impact

- `packages/troupe/src/troupe/core/runners/`: `effects.py` (the audit's findings as a value, and its verdict from
  them), `host.py` (runs the audit after any started run), `outcome.py` (`RunOutcome` carries the audit).
- `packages/troupe/src/troupe/core/runs/perform.py` (passes the expected files and the audit apart),
  `projections.py` (the summary's `audit`); `core/client/messages.py` (`RunSummary.audit`).
- `packages/troupe/src/troupe/cli/render.py` and `commands.py` (status and logs).
- `protocol/schemas/events/run-ended.schema.json`, `protocol/schemas/client/run.schema.json`, and their packaged
  copies.
- The conformance suite and host tests, which have no workspace to audit, say so explicitly.
- `docs/the-company/performances-and-runs.md` and the CLI reference, where they describe the audit and status.
- No spec is added or removed and no Purpose changes, so troupe-run/infrastructure's `oob/troupe-spec-purposes.json`
  needs no update.
