## MODIFIED Requirements

### Requirement: A performance's start is recorded with its first run's start
A performance's start SHALL be recorded in the same batch as its first run's start, so that neither is ever recorded
without the other. It SHALL hold what was performed (`actor` or `flow`, and its name), its steps in order (each step's
actor, and its approvers with where they came from: `step`, `actor` or `default`), the direction's reference, and the
config version.

#### Scenario: The start of an actor's performance
- **WHEN** a person performs `tester`, which sets no approvers and works in a worktree, with direction `fix the tests`
- **THEN** the performance's start says an actor named `tester` was performed, with one step whose actor is `tester`
  and whose approvers are `troupe, director` from the `default`
- **AND** its direction reference is the run's direction reference, and its config version is the run's

#### Scenario: The start of a flow's performance
- **WHEN** a person performs the flow `review` (writer, then reviewer with `approvers: [director]`)
- **THEN** the performance's start says a flow named `review` was performed, with two steps: writer's with approvers
  from `default`, and reviewer's with `director` from `step`

#### Scenario: A start that can't be recorded
- **WHEN** a performance's batch can't be written because the config version it names is gone
- **THEN** neither the performance's start nor the run's start is recorded

### Requirement: A run's start names its step
A run's start SHALL name its step in its performance, counting from 1.

#### Scenario: An actor's run
- **WHEN** a person performs `tester`
- **THEN** the run's start names step 1, and the run's lineage names the performance

#### Scenario: A flow's second run
- **WHEN** the flow `review` (writer, reviewer) reaches reviewer
- **THEN** reviewer's run start names step 2, and its lineage names the same performance as writer's

### Requirement: A run is listed and summarised with its performance
`status` SHALL list one line per performance. A performance of one step SHALL be listed as its run, naming the
performance; a flow's line SHALL show its name and progress (the running, waiting or failed step, or its end), with each
of its runs on its own indented line. Every run summary SHALL name the run's performance and its step.

#### Scenario: Status names the performance and step
- **WHEN** a person runs `status <run>` for a run started by `troupe perform tester`
- **THEN** its summary names the performance `perform` printed, and step 1

#### Scenario: Perform's result names the performance
- **WHEN** a person performs `tester` and its run ends
- **THEN** the run summary in perform's result names the performance and step 1

#### Scenario: A flow waiting at a step
- **WHEN** the flow `review` waits after step 1 of 2 and a person runs `troupe status`
- **THEN** one line names the performance, `review` and `waiting at step 1/2`, and writer's run is listed under it

## ADDED Requirements

### Requirement: A performance id is taken wherever a run id is
Wherever a command or query takes a run, it SHALL also take a performance's full id, or a prefix of at least 8 hex
digits matching exactly one run or performance. `approve` and `reject` SHALL act on the performance's step waiting at a
gate, refused with `gate.no-cue` when none waits. `accept`, `discard` and `diff` SHALL act on the performance's work as
a whole. `status` and `logs` SHALL show the performance and every step.

#### Scenario: Approving through the performance
- **WHEN** a flow's step 2 waits at its gate and a person runs `troupe approve <performance>`
- **THEN** step 2's run is approved

#### Scenario: Diffing a flow's work so far
- **WHEN** a flow failed at step 3 after steps 1 and 2 changed files, and a person runs `troupe diff <performance>`
- **THEN** it shows steps 1 to 3's changes as one diff against the performance's base

#### Scenario: Diffing through an actor's performance
- **WHEN** a person runs `troupe diff <performance>` for a worktree run's performance
- **THEN** it shows the run's diff

#### Scenario: A prefix that matches a run and a performance
- **WHEN** a run's id and another performance's id both start with `1a2b3c4d`, and a person asks for
  `status 1a2b3c4d`
- **THEN** it is refused with `run.ambiguous-id`, listing the run and the performance


### Requirement: Naming one run of a flow's work refuses settling it alone
`accept` and `discard` given a run of a performance of more than one step SHALL be refused with
`performance.settled-whole`, naming the performance to settle instead, since each step builds on the ones before.

#### Scenario: Discarding one step
- **WHEN** a two-step performance failed at step 2, and a person runs `troupe discard <step 1's run>`
- **THEN** it is refused with `performance.settled-whole`, naming the performance, and nothing is removed

## REMOVED Requirements

### Requirement: A performance id names a run where a run id does
**Reason**: A performance now has several runs, so a performance id names the performance, and each command acts on
it as "A performance id is taken wherever a run id is" says. `performance.several-runs` is retired with it.
**Migration**: None needed: every performance id that named a run still works, and names the same work.

