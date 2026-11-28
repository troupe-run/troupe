## Purpose

Capability: `cap:flows`, `cap:config`, `cap:performance`

Defines a flow in config, an ordered list of steps that each name an actor, and performs it as one performance whose
steps run in sequence, each building on the work before it, unattended unless a gate stops it.

## ADDED Requirements

### Requirement: A flow is a config kind of its own
Config SHALL have a kind `flows`, beside actors and runtimes: `flows.<name>` holds `steps`, an ordered list. Each step
SHALL name an `actor`, and MAY give its own `direction` (text) and `approvers` (as an actor's). A flow's name SHALL
follow the actor name rule. Config commands SHALL set, get, unset and rename flows as they do actors.

#### Scenario: A flow set by command
- **WHEN** a person runs `troupe config set 'flows.review.steps=[{"actor": "writer"}, {"actor": "reviewer", "direction": "review what the writer changed"}]'`
- **THEN** config holds the flow `review` with those two steps, in that order

#### Scenario: A step's approvers
- **WHEN** a flow's second step sets `approvers: [director]`
- **THEN** config holds it, checked by the same rules as an actor's approvers

### Requirement: A flow's steps must be performable
Config SHALL refuse a flow with no steps, a step naming an actor config doesn't have, and a step whose actor works in
the theatre, naming the flow, the step and the rule. Removing an actor a flow names, or setting it to work in the
theatre, SHALL be refused the same way. A merge that leaves any of these SHALL be a conflict. The same actor MAY appear
in more than one step.

#### Scenario: An actor that doesn't exist
- **WHEN** a person sets a flow whose step names `nobody`
- **THEN** it is refused, naming the flow, the step and that no actor `nobody` exists, and nothing is recorded

#### Scenario: Removing an actor a flow uses
- **WHEN** a person runs `troupe config unset actors.writer` while the flow `review` names it
- **THEN** it is refused, naming `review`, and nothing is recorded

#### Scenario: A step working in the theatre
- **WHEN** a person sets a flow whose step names an actor with `workspace: theatre`
- **THEN** it is refused, naming the step and the actor's workspace

#### Scenario: The same actor twice
- **WHEN** a person sets a flow whose steps are writer, reviewer, writer
- **THEN** config holds the flow

### Requirement: Flows and actors share one namespace
A flow SHALL NOT have the name of an actor. Setting either with the other's name SHALL be refused, naming both, and a
merge that leaves both SHALL be a conflict.

#### Scenario: A flow named like an actor
- **WHEN** config has the actor `review` and a person sets the flow `review`
- **THEN** it is refused, naming the actor `review`, and nothing is recorded

### Requirement: Performing a flow runs its steps in order
`troupe perform <name>` SHALL perform the flow when `<name>` is a flow, recording one performance whose steps are the
flow's steps, and running each step's actor as a run, one after another, until the last step's gate, a gate that
waits, or a step that doesn't succeed. A rehearsal SHALL check every step's actor and run nothing; one refusal refuses
the whole flow.

#### Scenario: A flow that runs to the end
- **WHEN** a person performs the flow `review` (writer, reviewer), each run succeeds and troupe approves each gate
- **THEN** one performance is recorded with two steps, writer's run is step 1 and reviewer's is step 2, and the
  performance ends `completed`

#### Scenario: A rehearsal with one refused step
- **WHEN** a person rehearses a flow whose second step's runtime has no credential
- **THEN** it is refused with that step's error, and no performance or run is recorded

### Requirement: Perform names each step as it starts
For a flow, `perform` SHALL send the performance's start once, naming the flow and its number of steps, then each
step's run id, step number and actor as the step starts. The CLI SHALL write `troupe: performance <id> (<flow>,
<n> steps) starting`, then `troupe: step <k>/<n> <actor>: run <id> starting` for each step.

#### Scenario: Progress through a flow
- **WHEN** a person performs the flow `review` (writer, reviewer)
- **THEN** standard error names the performance and `review, 2 steps`, then `step 1/2 writer`, then `step 2/2
  reviewer`, each with its run id

### Requirement: Each step works on the steps before it
Each step SHALL work in its own worktree, made at the performance's base commit with the performance's changes so far
applied to it, all or nothing. A step's diff SHALL hold only what that step changed, and its audit SHALL judge only
those changes. The person's files SHALL NOT change until the last step's gate.

#### Scenario: The second step sees the first's work
- **WHEN** step 1 writes `src/a.txt` and step 2's runner reads it
- **THEN** step 2 reads step 1's content, and step 2's diff doesn't hold step 1's change

#### Scenario: Nothing reaches the person's files mid-flow
- **WHEN** a flow's first step has run and its second is running
- **THEN** the theatre's own files are as they were before the perform

### Requirement: A step is told the performance's direction, its own, and the step before
A step's direction SHALL hold, in order: the performance's direction; the step's own direction, when it has one; the
previous step's brief in full (its actor, outcome, files changed and final message); and one line for each earlier
step, naming its actor, outcome, number of files and where its history files are. It SHALL be stored by reference as
any direction is. A first step SHALL be told what a run is told today.

#### Scenario: The third step's direction
- **WHEN** a flow of writer, reviewer, tester performs with direction `add a --json flag`, reviewer's step direction is
  `review what the writer changed`, and tester starts
- **THEN** tester's direction holds `add a --json flag`, reviewer's full brief, and one line each for writer and
  reviewer

### Requirement: Earlier steps' history is readable in each step's worktree
Before a step's runner starts, its worktree SHALL hold `.troupe/performance/<n>-<actor>/` for each earlier step, with
`brief.md`, `changes.diff` (its diff, when it had changes) and `log.md` (its log as `troupe logs` shows it, credentials
masked). No tool SHALL change them, and they SHALL NOT be part of any diff.

#### Scenario: Reading an earlier step's diff
- **WHEN** tester, step 3, reads `.troupe/performance/1-writer/changes.diff`
- **THEN** it reads writer's diff

#### Scenario: History isn't a change
- **WHEN** a step ends having changed only `src/a.txt`
- **THEN** its diff names `src/a.txt` alone

### Requirement: A step's approvers come from the step, its actor, or the default
A step's gate SHALL try the step's own approvers when it sets them, else its actor's, else `[troupe, director]`. The
performance's start and the step's run start SHALL record them with where they came from: `step`, `actor` or
`default`.

#### Scenario: Approvers set on the step
- **WHEN** a flow's step sets `approvers: [director]` and its actor sets none
- **THEN** the step's run start records `director` from `step`

### Requirement: Before the last step, approving lets the work go on
At every step before the last with changes, approving SHALL record `Run.ChangesApproved` on the step's run, carrying
the approval, and the next step SHALL start. troupe SHALL approve such a gate when the step's changes apply to the
performance's work so far. A step that changes nothing SHALL reach no gate, and the next step SHALL start.

#### Scenario: troupe lets a step through
- **WHEN** step 1 of 2 succeeds with changes and its approvers are the default
- **THEN** step 1's run records `Run.ChangesApproved` with troupe's approval in role `troupe`, and step 2 starts

#### Scenario: A person first, mid-flow
- **WHEN** step 1 of 2 succeeds with changes and its approvers are `[director]`
- **THEN** a cue is raised for `director`, step 2 doesn't start, `perform` exits 4, and the performance has no end

### Requirement: The last step's gate lands the whole flow
The last step's gate SHALL be passed whenever the performance has changes, even if the last step had none. Keeping
the work SHALL apply the performance's whole diff to the person's files, all or nothing, recorded as
`Run.ChangesAccepted` on the last step's run, and a conflict SHALL pass to `director` as a single run's gate does.

#### Scenario: A flow landing
- **WHEN** writer and reviewer both change files and troupe keeps the work at reviewer's gate
- **THEN** the theatre's files hold both steps' changes, and the performance ends `completed`

#### Scenario: A last step with no changes
- **WHEN** writer changes `src/a.txt` and the last step, tester, changes nothing
- **THEN** tester's gate is passed with the performance's diff, and `src/a.txt` lands

### Requirement: Approving a waiting step carries the flow on
`troupe approve` on a step waiting before the last SHALL record its approval and run the remaining steps in the
foreground, sending perform's updates and exiting as `perform` does. The remaining steps SHALL use config as it was at
the performance's start. `--rehearse` SHALL check the remaining steps and run nothing.

#### Scenario: Carrying on after an approval
- **WHEN** a flow waits after step 1 of 2, and a person runs `troupe approve <performance> --reason "looks right"`
- **THEN** step 2 runs, its gate lands the work, and approve exits 0

#### Scenario: Config edited while the flow waits
- **WHEN** a person changes step 2's actor's options while the flow waits after step 1, then approves
- **THEN** step 2 runs with the options the actor had when the performance started

### Requirement: A stopped flow stops whole
Rejecting a step SHALL end the performance `rejected` and remove every worktree it made. A step that doesn't succeed
SHALL end it `failed` (`cancelled` for Ctrl-C), with nothing after it run, and its work so far SHALL be accepted or
discarded only as a whole, through the performance. A waiting performance SHALL NOT time out.

#### Scenario: A failed second step
- **WHEN** step 2 of 3 fails after step 1 changed files
- **THEN** step 3 doesn't run, the performance ends `failed`, and `troupe accept <performance>` applies steps 1 and 2's
  changes together

#### Scenario: Naming one of a failed flow's runs
- **WHEN** a person runs `troupe accept` with step 1's run id from a failed two-step performance
- **THEN** it is refused with `performance.settled-whole`, naming the performance
