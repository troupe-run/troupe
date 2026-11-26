# Spec Delta

## Purpose

Capability: `cap:gates`, `cap:cues`

Decides whether a worktree run's work is kept. Each run passes a gate when it ends, and its actor's approvers are
tried in order: troupe keeps clean work by itself, and a role it can't act for gets a cue that a person answers with
approve or reject. Every step is recorded with lineage.

## ADDED Requirements

### Requirement: A worktree run that succeeds with changes passes a gate
When a worktree run ends `succeeded` with a captured diff, troupe SHALL take it through a gate before anything else
can settle its changes. A run that ends any other way, a run whose changes are `none` or `uncaptured`, and a run
whose workspace is `theatre`, SHALL reach no gate, and its changes SHALL be settled as they are without gates.

#### Scenario: A succeeded run with changes
- **WHEN** a worktree run changes `src/a.txt` and ends `succeeded`
- **THEN** its approvers are tried in order, starting with the first

#### Scenario: A failed run with changes
- **WHEN** a worktree run writes `out/partial.txt` and ends `failed`
- **THEN** no gate is reached, its changes are `pending`, and `troupe accept` or `troupe discard` settles them

#### Scenario: A run that changed nothing
- **WHEN** a worktree run ends `succeeded` and changed no file
- **THEN** no gate is reached, and its changes are `none`

### Requirement: Approvers are tried in order
A gate SHALL try the run's approvers in the order they're listed. Each SHALL either answer, approving or rejecting
the work, or pass the gate to the next approver when it can't act. A gate SHALL stop at the first answer.

#### Scenario: The default list on a clean run
- **WHEN** a run's approvers are `[troupe, director]` and its diff applies cleanly to the working tree
- **THEN** `troupe` approves, the changes are kept, and no cue is raised

#### Scenario: The default list on a conflict
- **WHEN** a run's approvers are `[troupe, director]` and `src/a.txt` in the working tree conflicts with its diff
- **THEN** `troupe` passes the gate to `director`, and a cue is raised for `director`

#### Scenario: A person first
- **WHEN** a run's approvers are `[director]`
- **THEN** troupe doesn't try the diff, and a cue is raised for `director`

### Requirement: troupe approves clean changes by itself
The built-in approver `troupe` SHALL approve when the run's diff applies cleanly to the working tree, keeping the
changes as an accept does: applied unstaged, all or nothing, and the worktree removed. It SHALL never reject. When
the diff doesn't apply cleanly, it SHALL change no file and pass.

#### Scenario: Kept by troupe
- **WHEN** a run with approvers `[troupe, director]` modified `src/a.txt` and added `out/hello.txt`, and both apply
- **THEN** the theatre's `src/a.txt` and `out/hello.txt` are as the run left them, unstaged, and the worktree is gone
- **AND** the run's changes are `accepted`

#### Scenario: troupe can't keep them
- **WHEN** the run's diff doesn't apply cleanly to `src/a.txt`
- **THEN** no file in the theatre changes, and the worktree is still there

### Requirement: An approval is recorded in the lineage of the event that keeps the work
The event that keeps a run's work at a gate SHALL be the run's acceptance, and its lineage's `approvals` SHALL hold
one approval naming the approver's actor, the role it approved in, and when. An approval by `troupe` SHALL name the
system actor and the role `troupe`.

#### Scenario: troupe's approval
- **WHEN** `troupe` keeps a run's changes
- **THEN** the run's acceptance has a `system` actor, and `approvals` holds one entry with that actor and role
  `troupe`

#### Scenario: A person's approval
- **WHEN** a person whose identity resolves to `ada@example.com` approves a run's cue with `--reason "fine"`
- **THEN** the run's acceptance has actor `human` `ada@example.com`, reason `fine`, and `approvals` holding one
  entry with that actor and role `director`

### Requirement: A pass is recorded with its reason
When an approver passes a gate, troupe SHALL record the pass on the run's stream, naming the approver that passed,
why (for `troupe`, `conflict` and the files that don't apply), and the approver the gate goes to next.

#### Scenario: A pass on a conflict
- **WHEN** `troupe` can't apply a run's diff because of `src/a.txt`
- **THEN** the run's stream holds a pass from `troupe` to `director`, with reason `conflict` and the file
  `src/a.txt`

### Requirement: Reaching director raises a cue
When a gate reaches `director`, troupe SHALL record a cue on the run's stream, addressed to `director`, with a brief:
the actor, the run's outcome, how many files were added, modified and deleted, the diff's reference, and why it came
(first in the list, or passed from an approver, with the pass's reason). The run's changes SHALL be `waiting` while the cue is open.

#### Scenario: A cue after a pass
- **WHEN** `troupe` passes a run's gate to `director` on a conflict in `src/a.txt`
- **THEN** the run's stream holds a cue for `director`, whose brief names the actor, `succeeded`, the counts of files
  changed, the diff's reference, and the pass from `troupe` with `src/a.txt`
- **AND** `status <run>` shows its changes as `waiting` for `director`

#### Scenario: A cue first in the list
- **WHEN** a run with approvers `[director]` ends `succeeded` with changes
- **THEN** its cue is recorded with the run's end, so no `perform` that stops after the end leaves it unasked

### Requirement: Whoever runs troupe holds director
Until roles config exists, `director` SHALL be held by any person whose identity resolves in the theatre. An answer
from an identity whose kind is `agent` SHALL be refused with `gate.not-a-holder`, naming `director` and saying that
only a person holds it until roles config, and nothing SHALL be recorded.

#### Scenario: Another person on the same clone
- **WHEN** ada performs a run with approvers `[director]`, and bob approves its cue on the same clone
- **THEN** the approval names bob, in role `director`

#### Scenario: An agent identity
- **WHEN** `TROUPE_ACTOR` is `agent:bot` and `troupe approve <run>` is run
- **THEN** it is refused with `gate.not-a-holder`, and the cue stays open

### Requirement: Approving a cue keeps the work
`approve` SHALL answer a run's open cue by keeping its changes as an accept does, recorded with the approval. When
the diff doesn't apply cleanly, it SHALL be refused with `run.changes-conflict`, naming the files, and the cue SHALL
stay open. It SHALL take a reason and `rehearse`.

#### Scenario: Approving after fixing a conflict
- **WHEN** a run's cue came from a conflict in `src/a.txt`, the person restores `src/a.txt`, and runs
  `troupe approve <run> --reason "fine"`
- **THEN** the run's changes are in the working tree, the worktree is gone, and the run's changes are `accepted`

#### Scenario: Approving while it still conflicts
- **WHEN** a person approves a run whose diff still doesn't apply to `src/a.txt`
- **THEN** it is refused with `run.changes-conflict`, naming `src/a.txt`, no file changes, and the cue stays open

#### Scenario: Rehearsing an approve
- **WHEN** a person runs `troupe approve <run> --rehearse` and the diff applies cleanly
- **THEN** it names the files it would change, and no file or event changes

### Requirement: Rejecting a cue removes the worktree
`reject` SHALL answer a run's open cue by removing its worktree as a discard does, changing nothing in the working
tree, and recording the rejection with who rejected it, in which role, and the reason. The run's changes SHALL then
be `rejected`. It SHALL take a reason and `rehearse`.

#### Scenario: Rejecting
- **WHEN** a person runs `troupe reject <run> --reason "wrong file"`
- **THEN** the run's worktree is gone, the working tree is unchanged, and the run's changes are `rejected`
- **AND** the rejection's lineage names the person and reason `wrong file`, and records role `director`

#### Scenario: Rehearsing a reject
- **WHEN** a person runs `troupe reject <run> --rehearse`
- **THEN** it names the worktree it would remove, and no file or event changes

### Requirement: A cue is answered once
A second answer to a cue SHALL be refused with `run.changes-settled`, naming what was done and when. Answering a run
with no open cue SHALL be refused with `gate.no-cue`, saying what state its changes are in and, when they're
`pending`, naming `troupe accept` and `troupe discard`.

#### Scenario: Two approves at once
- **WHEN** two `approve`s of the same run start at the same time
- **THEN** one keeps the changes, and the other is refused with `run.changes-settled`

#### Scenario: Approving a run that never reached a gate
- **WHEN** a person approves a run that ended `failed` with changes
- **THEN** it is refused with `gate.no-cue`, naming `troupe accept` and `troupe discard`

#### Scenario: Approving a run troupe already kept
- **WHEN** a person approves a run whose changes `troupe` kept
- **THEN** it is refused with `run.changes-settled`, naming the acceptance and when

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

### Requirement: Approve and reject commands
The CLI SHALL offer `troupe approve <run>` and `troupe reject <run>`, each calling the core through the client
protocol, naming the run by id or unique prefix, and taking `--reason` and `--rehearse`. Each SHALL write what it did
to standard output: the files it kept, or the worktree it removed.

#### Scenario: Approve
- **WHEN** a person runs `troupe approve <run> --reason "fine"` on a run waiting for `director`
- **THEN** it exits 0, the run's changes are in the working tree, and standard output names the run and the files

#### Scenario: Reject
- **WHEN** a person runs `troupe reject <run> --reason "wrong file"` on a run waiting for `director`
- **THEN** it exits 0, and standard output names the run and the worktree it removed

#### Scenario: Rehearsing an approve
- **WHEN** a person runs `troupe approve <run> --rehearse` and the diff applies cleanly
- **THEN** it exits with the "would change" code and names the files it would change, and nothing changes

### Requirement: Status shows open cues and a run's gate
`troupe status` SHALL show the open cues before the runs, one line each with the run, its actor, the role and when the
cue was raised. `troupe status <run>` SHALL show the run's approvers with their source and its gate's steps, and the
run list SHALL show a waiting run's changes as `waiting` with the role.

#### Scenario: An open cue in the list
- **WHEN** a run of `writer` waits for `director`, and a person runs `troupe status`
- **THEN** standard output starts with a line naming the run, `writer`, `director` and when the cue was raised

#### Scenario: A run's approvers
- **WHEN** a person runs `troupe status <run>` for a run of an actor with no approvers set
- **THEN** it shows `approvers: troupe, director (default)`
