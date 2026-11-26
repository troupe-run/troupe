# Spec Delta

## ADDED Requirements

### Requirement: A worktree run's start records its approvers and where they came from
A worktree run's start SHALL record its approvers, in order, with their source: `actor` when the actor sets them, or
`default` when they're the built-in default. A run whose workspace is `theatre` SHALL record no approvers.

#### Scenario: An actor that sets none
- **WHEN** a worktree actor with no `approvers` is performed
- **THEN** its run's start records approvers `troupe`, `director`, with source `default`

#### Scenario: An actor that sets them
- **WHEN** a worktree actor with approvers `[director]` is performed
- **THEN** its run's start records approvers `director`, with source `actor`

#### Scenario: A run in place
- **WHEN** an actor whose workspace is `theatre` is performed
- **THEN** its run's start has no approvers

#### Scenario: A rehearsal shows them
- **WHEN** a person runs `troupe perform tester --rehearse` for a worktree actor with no `approvers`
- **THEN** it shows approvers `troupe, director` with source `default`, and nothing is recorded

### Requirement: A run's summary shows its gate
A worktree run's summary SHALL show its approvers with their source, and, once it has passed a gate, each step in
order: a pass with the approver, its reason and files, a cue with the role it's for and when it was raised, and the
answer with who gave it, in which role, the reason and when.

#### Scenario: A run kept by troupe
- **WHEN** a person runs `status <run>` for a run `troupe` kept
- **THEN** it shows approvers `troupe, director (default)`, and that `troupe` approved it, and when

#### Scenario: A run approved by a person after a pass
- **WHEN** a person runs `status <run>` for a run `troupe` passed on a conflict in `src/a.txt` and ada then approved
- **THEN** it shows the pass with `src/a.txt`, the cue for `director`, and ada's approval as `director` with the
  reason ada gave

### Requirement: Status lists every open cue
`status` without a run SHALL list every run with an open cue, whatever the limit on runs listed, each with its actor,
the role the cue is for and when it was raised, before the runs. When no cue is open, it SHALL list none.

#### Scenario: A waiting run beyond the limit
- **WHEN** a run waiting for `director` is older than the last 20 runs, and a person runs `troupe status`
- **THEN** the run is listed among the open cues, with its actor, `director` and when its cue was raised

#### Scenario: Nothing waiting
- **WHEN** no run has an open cue
- **THEN** `troupe status` lists no open cues

### Requirement: Logs show a run's gate after its events
`logs` SHALL return a run's gate steps after its events and notices, in the order they were recorded: a pass, a cue,
and the answer that kept or rejected the work, each with the time it was recorded. Following SHALL stop at the run's
end, as it does today, so a gate's steps are shown by the next `logs` or `status`.

#### Scenario: Logs of a run that waited
- **WHEN** a person asks for the logs of a run whose cue ada approved
- **THEN** the log ends with the cue for `director` and ada's approval, after the run's result
