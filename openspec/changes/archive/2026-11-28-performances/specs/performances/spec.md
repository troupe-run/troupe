## Purpose

Capability: `cap:runs`, `cap:lineage`

Records every perform as a performance: one run of your process, with its own id, its start and its end, whose
steps are runs, so that whatever a perform caused can be found from the performance, and a performance id names its
run.

## ADDED Requirements

### Requirement: Every perform records a performance
Every `perform` that starts a run SHALL record a performance around it. The performance SHALL be its own stream,
identified by a new UUID in canonical lowercase form minted by `perform`. Performing an actor SHALL record a
performance of one step, whose run is the actor's run. A refused or rehearsed `perform` SHALL record no performance.

#### Scenario: Performing an actor
- **WHEN** a person performs the actor `tester`
- **THEN** one performance is recorded, with one step whose actor is `tester`, and the run `perform` started is that
  step's run

#### Scenario: A refused perform
- **WHEN** a person performs an actor that policy refuses
- **THEN** no performance and no run is recorded

#### Scenario: A rehearsed perform
- **WHEN** a person performs an actor with `--rehearse`
- **THEN** no performance and no run is recorded

### Requirement: A performance's start is recorded with its first run's start
A performance's start SHALL be recorded in the same batch as its first run's start, so that neither is ever recorded
without the other. It SHALL hold what was performed (`actor` and its name), its steps in order (each step's actor,
and its approvers with where they came from when the actor works in a worktree), the direction's reference, and the
config version.

#### Scenario: The start of an actor's performance
- **WHEN** a person performs `tester`, which sets no approvers and works in a worktree, with direction `fix the tests`
- **THEN** the performance's start says an actor named `tester` was performed, with one step whose actor is `tester`
  and whose approvers are `troupe, director` from the `default`
- **AND** its direction reference is the run's direction reference, and its config version is the run's

#### Scenario: A start that can't be recorded
- **WHEN** a performance's batch can't be written because the config version it names is gone
- **THEN** neither the performance's start nor the run's start is recorded

### Requirement: A run's start names its step
A run's start SHALL name its step in its performance, counting from 1. Until flows, every run is step 1 of a
performance of one step.

#### Scenario: An actor's run
- **WHEN** a person performs `tester`
- **THEN** the run's start names step 1, and the run's lineage names the performance

### Requirement: A performance ends once nothing more will happen in it
A performance's end SHALL be recorded once nothing more will happen in it, with its outcome:

- `completed`: every step ran, and the work was kept or there was none.
- `failed`: a step didn't succeed, or its changes couldn't be captured.
- `rejected`: its work was turned down at a gate or discarded.
- `cancelled`: a step was cancelled.

A performance whose work waits at a gate, or whose `perform` stopped without an end, SHALL have no end until a
person settles its run.

#### Scenario: A run that succeeds without changes
- **WHEN** a person performs an actor whose run succeeds and changes nothing
- **THEN** the performance ends `completed`, in the same batch as the run's end

#### Scenario: Work troupe keeps
- **WHEN** a worktree run succeeds with changes that troupe keeps at its gate
- **THEN** the performance ends `completed`, in the same batch as the acceptance

#### Scenario: A failed run
- **WHEN** a person performs an actor whose run fails
- **THEN** the performance ends `failed`, in the same batch as the run's end, and the run's changes still wait for
  accept or discard

#### Scenario: A run whose changes couldn't be captured
- **WHEN** a worktree run succeeds and capturing its changes fails, so they're `uncaptured`
- **THEN** the performance ends `failed`, in the same batch as the run's end, since its work can never reach its gate

#### Scenario: A cancelled run
- **WHEN** a person presses Ctrl-C during a run
- **THEN** the performance ends `cancelled`, in the same batch as the run's end

#### Scenario: Work waiting at a gate
- **WHEN** a run's work waits at its gate with a cue open to `director`
- **THEN** the performance has no end

### Requirement: Answering a gate ends a waiting performance
When a person approves a cue, the performance SHALL end `completed` in the same batch as the acceptance. When a
person rejects one, it SHALL end `rejected` in the same batch as the rejection.

#### Scenario: Approving
- **WHEN** a person runs `troupe approve <run>` on a run waiting at its gate
- **THEN** the run's acceptance and the performance's end, `completed`, are recorded together

#### Scenario: Rejecting
- **WHEN** a person runs `troupe reject <run>` on a run waiting at its gate
- **THEN** the run's rejection and the performance's end, `rejected`, are recorded together

#### Scenario: Accepting a failed run's changes
- **WHEN** a person accepts the changes of a run that failed
- **THEN** the acceptance is recorded, and the performance, which ended `failed` with the run, records nothing more

### Requirement: A performance's end is recorded once
A performance SHALL have at most one end, and nothing SHALL be recorded in its stream after it. A second end SHALL be
refused as a fault, and nothing SHALL be written for it.

#### Scenario: A second end
- **WHEN** an end is recorded for a performance that has ended
- **THEN** recording fails with `performance.out-of-sequence`, and nothing is written

### Requirement: A performance id names a run where a run id does
Wherever a command or query takes a run, it SHALL also take a performance's full id, or a prefix of at least 8 hex
digits that matches exactly one run or performance. A performance id SHALL name the performance's run when it has
exactly one; otherwise the command SHALL be refused with `performance.several-runs`, listing its runs.

#### Scenario: Approving through the performance
- **WHEN** an actor's run waits at its gate and a person runs `troupe approve <performance>`
- **THEN** the run is approved, as `troupe approve <run>` would approve it

#### Scenario: Diffing through the performance
- **WHEN** a person runs `troupe diff <performance>` for a worktree run's performance
- **THEN** it shows the run's diff

#### Scenario: A performance with several runs
- **WHEN** a performance's stream and two runs that name it are recorded, and a person runs `troupe diff
  <performance>`
- **THEN** it is refused with `performance.several-runs`, listing both runs

#### Scenario: A prefix that matches a run and a performance
- **WHEN** a run's id and another performance's id both start with `1a2b3c4d`, and a person asks for
  `status 1a2b3c4d`
- **THEN** it is refused with `run.ambiguous-id`, listing the run and the performance

### Requirement: A run recorded before performances is refused with its fix
Reading runs back SHALL refuse a store holding any run whose start names no performance, with
`run.recorded-before-performances`, listing every such run and the event files that hold their events, saying which
of those files hold other events too. Its fix SHALL say to read them with a troupe before 0.5, or to remove and
commit the files that hold nothing else. It SHALL NOT be read without a performance or skipped.

#### Scenario: A run from before performances
- **WHEN** a theatre's committed events hold a run whose start's lineage has no `performance`, alone in its file,
  and a person runs `troupe status`
- **THEN** it is refused with `run.recorded-before-performances`, naming the run and its file as one that holds
  nothing else

#### Scenario: A file shared with a config change
- **WHEN** such a run's start is in the same file as a config change, and a person runs `troupe status`
- **THEN** the refusal names that file as one that holds other events, to keep

#### Scenario: Perform refuses before it runs anything
- **WHEN** a theatre holds such a run, and a person performs an actor, for real or with `--rehearse`
- **THEN** it is refused with `run.recorded-before-performances` before any performance or run is recorded, and
  no runner starts

### Requirement: A run is listed and summarised with its performance
A performance of one step SHALL be listed by `status` as its run, naming the performance. Every run summary that
`status`, `logs` and `perform` return SHALL name the run's performance and its step.

#### Scenario: Status names the performance and step
- **WHEN** a person runs `status <run>` for a run started by `troupe perform tester`
- **THEN** its summary names the performance `perform` printed, and step 1

#### Scenario: Perform's result names the performance
- **WHEN** a person performs `tester` and its run ends
- **THEN** the run summary in perform's result names the performance and step 1

### Requirement: The CLI shows a performance before its run
`troupe perform`'s standard output on success SHALL name the performance, then the run, then `succeeded`. Each line of
`troupe status`'s list SHALL start with the performance's id, and `troupe status <run>` SHALL show the run's
performance and its step.

#### Scenario: A successful run
- **WHEN** a person performs `tester` and its run ends `succeeded`
- **THEN** standard output is one line naming the performance, the run and `succeeded`

#### Scenario: The list starts each line with the performance
- **WHEN** a person has performed `tester` and runs `troupe status`
- **THEN** the line for that perform starts with the performance's id, then names the run and its state as before

#### Scenario: A run's summary names its performance
- **WHEN** a person runs `troupe status <run>`
- **THEN** the summary shows the run's performance and its step

### Requirement: Settling a run ends a performance its perform left open
When a person's `accept` or `discard` settles a run whose performance has no end, the performance SHALL end in the
same batch: `completed` for an accept, `rejected` for a discard. This covers a perform that stopped after its run's
end and before troupe's turn at the gate, or before the run's end. A performance that has ended SHALL record nothing
more.

#### Scenario: Accepting after perform stopped before troupe's turn
- **WHEN** a run succeeds with changes, its perform stops before troupe's turn at the gate, and a person runs
  `troupe accept <run>`
- **THEN** the acceptance and the performance's end, `completed`, are recorded together

#### Scenario: Discarding an interrupted run
- **WHEN** a person runs `troupe discard <run>` for a run whose perform stopped without recording its end
- **THEN** the discard and the performance's end, `rejected`, are recorded together
