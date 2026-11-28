## MODIFIED Requirements

### Requirement: An approval is recorded in the lineage of the event that keeps the work
The event that lets a run's work through its gate SHALL carry the approval: the run's acceptance when the gate keeps
the work, or `Run.ChangesApproved` when it lets a flow's step go on. Its lineage's `approvals` SHALL hold one approval
naming the approver's actor, the role it approved in, and when. An approval by `troupe` SHALL name the system actor and
the role `troupe`.

#### Scenario: troupe's approval
- **WHEN** `troupe` keeps a run's changes
- **THEN** the run's acceptance has a `system` actor, and `approvals` holds one entry with that actor and role
  `troupe`

#### Scenario: A person's approval
- **WHEN** a person whose identity resolves to `ada@example.com` approves a run's cue with `--reason "fine"`
- **THEN** the run's acceptance has actor `human` `ada@example.com`, reason `fine`, and `approvals` holding one
  entry with that actor and role `director`

#### Scenario: Letting a step go on
- **WHEN** `troupe` approves a flow's first step of two
- **THEN** the step's run records `Run.ChangesApproved`, and its `approvals` holds troupe's, in role `troupe`

### Requirement: Approving a cue keeps the work
`approve` SHALL answer a run's open cue at the last step of its performance by keeping the performance's changes as an
accept does, recorded with the approval, and at an earlier step by letting the work go on (spec: flows). When the
diff doesn't apply cleanly, it SHALL be refused with `run.changes-conflict`, naming the files, and the cue SHALL stay
open. It SHALL take a reason and `rehearse`.

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
