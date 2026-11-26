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
