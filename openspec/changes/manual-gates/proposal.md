# Proposal: gates, and the approvers who let a run's work through

## Why

Every worktree run's changes wait for a person today: `troupe perform` ends with them pending, and nothing is kept
until someone runs `troupe accept`. "Needing to accept every run defeats the purpose of what we are orchestrating"
(owner, 2026-11-26). Nothing records that wait as an approval either: `approvals` is empty in every event, and nothing
says which runs must wait or lists what's waiting. troupe-run/troupe#62 settles the first slice of gates (0.4.0),
with the owner's decisions 1 to 9 recorded on the issue.

## What Changes

- **Approvers on the actor.** A new optional actor field, `approvers`, holds an ordered list of roles that may let a
  worktree run's work through. When it's absent, the built-in default is `[troupe, director]`. Until roles config,
  a list may name only `troupe` and `director`. It must end in `director`, and `troupe` may come only first. An
  empty list or a repeated name is refused, and so is a list on an actor whose workspace is `theatre`.
- **A gate at the end of every worktree run** that succeeded with changes. Its approvers are tried in order.
  `troupe` approves when the diff applies cleanly, and the changes are kept as an accept keeps them. When the diff
  doesn't apply, `troupe` passes the gate to the next role, and the pass is recorded with the conflicting files.
  Reaching `director` raises a cue: an open request on the run's stream, with a brief.
- **`troupe approve <run>` and `troupe reject <run>`**, new commands with `--reason` and `--rehearse`, answer a cue.
  Approve keeps the work and records the approval. Reject removes the worktree and records the rejection.
- **BREAKING:** a worktree run that succeeds with changes and has no `approvers` set is now kept when it ends,
  instead of waiting for `troupe accept`. This changes 0.1.0's "keep or discard" default.
- **BREAKING:** `troupe accept` and `troupe discard` are refused on a run whose cue is open, naming `troupe approve`
  or `troupe reject`.
- **Lineage records approvals.** The event that keeps a run's work carries who approved it, and in which role. An
  approval by `troupe` names a new actor kind, `system`, which #15 decided for troupe acting by itself. This is a
  protocol change to the lineage schema.
- **A run records its approvers** and where they came from (`actor` or `default`) when it starts. `troupe status`
  shows them, lists open cues, and gives the gate's steps for a run. So do `troupe logs` and the run summary.
- **`troupe perform` exits with a new code, 4,** when the run succeeded and its work waits at a gate. Its output says
  whether the work was kept or is waiting, and for whom.
- **`troupe init --audition`'s actor sets `approvers: [director]`** for every runner, so the first run still asks.
  The first-run docs say how to drop the wait.

## Capabilities

### New Capabilities

- `gates`: the gate at the end of a worktree run. Covers the approvers list and its rules, the built-in `troupe` and
  `director` roles, passing to the next role, the cue and its brief, and answering it with approve or reject.

### Modified Capabilities

- `config`: the actor gains `approvers`, checked when set or swept. Every audition's actor sets `[director]`.
- `run-workspaces`: accept and discard are refused while a cue is open. A worktree is kept until its work is kept,
  approved, rejected or discarded, and the run's changes state covers waiting at a gate.
- `runs`: a run's start records its approvers and their source. The run summary and logs show the gate's steps, and
  status lists open cues.
- `lineage`: the actor kind `system`, and approvals filled in by gates.
- `cli`: `troupe approve` and `troupe reject`. `perform`'s exit code and end-of-run output reflect the gate. Init's
  audition sets approvers.
- `user-docs`: the first-run walkthrough approves instead of accepting, and the glossary defines approver.

## Impact

- **Protocol:** the actor config schema (`approvers`); the lineage schema (`system` actor kind); new run event
  payload schemas (the gate's pass, the cue, the rejection); new client-protocol requests and results for approve and
  reject; run-summary and status results (approvers, their source, cues); new error codes in the catalogue.
- **Core:** the end of a worktree run (after capture), accept and discard, the run-summary projection, config
  validation of actors, and the audition definitions.
- **CLI:** the new commands, `perform`'s output and exit code (a new `ExitCode` member), and status and logs
  rendering.
- **Docs:** the first-run pages, gates and decisions, route decisions, read the lineage, the glossary, and the
  generated config, events, errors and CLI reference.
- **Not touched:** `core/config/merge.py` (#506 has it). Roles config (#148, #61), escalations (#126), sequences
  (#124) and cross-install answers (#12) build on this later.
- A new spec, `gates`, needs its Purpose recorded in troupe-run/infrastructure's `oob/troupe-spec-purposes.json`, in
  a pull request merged after this one.
