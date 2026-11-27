## ADDED Requirements

### Requirement: Perform says a waiting run succeeded and why it exits 4
When `troupe perform`'s run succeeds and its work waits at its gate, its message on standard error SHALL say the run
succeeded, name the role its work waits for, and say that exit 4 means waiting for that role, not failure. It SHALL
still name the worktree and `troupe diff`, `troupe approve` and `troupe reject` for the run.

#### Scenario: A first run waits for director
- **WHEN** a worktree run of an actor with approvers `[director]` ends `succeeded` with changes
- **THEN** standard error says the run succeeded and its work waits at its gate for `director`
- **AND** it says exit 4 means waiting for `director`, not failure, and names the worktree and `troupe diff`,
  `troupe approve` and `troupe reject` for the run
- **AND** `troupe perform` exits 4

#### Scenario: A waiting run after a conflict
- **WHEN** a worktree run's gate raises a cue for `director` after `troupe` passed on a conflict in `src/a.txt`
- **THEN** standard error says the run succeeded, that its work waits for `director` because `src/a.txt` conflicts,
  and that exit 4 means waiting, not failure
