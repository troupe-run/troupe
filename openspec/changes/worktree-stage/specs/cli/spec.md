# Spec Delta

## ADDED Requirements

### Requirement: Diff, accept and discard commands
The CLI SHALL offer `troupe diff <run>`, `troupe accept <run>` and `troupe discard <run>`, each calling the core
through the client protocol and naming the run by id or unique prefix. `troupe diff` SHALL write the diff to standard
output exactly as captured, and SHALL take `--json`. `troupe accept` and `troupe discard` SHALL take `--reason` and
`--rehearse`.

#### Scenario: A diff to pipe
- **WHEN** a person runs `troupe diff <run>` for a run with pending changes
- **THEN** standard output is the captured diff byte for byte, and `git apply --check` accepts it at the base commit

#### Scenario: A diff as JSON
- **WHEN** a person runs `troupe diff <run> --json`
- **THEN** standard output is one JSON document that validates against the `diff` result schema

#### Scenario: Accept
- **WHEN** a person runs `troupe accept <run> --reason "looks right"`
- **THEN** the run's changes are in the working tree, and standard output names the run and the files changed

#### Scenario: Rehearsing an accept
- **WHEN** a person runs `troupe accept <run> --rehearse` and the diff applies cleanly
- **THEN** it exits with the "would change" code and names the files it would change, and nothing changes

#### Scenario: A conflicting accept
- **WHEN** a person runs `troupe accept <run>` and the diff doesn't apply cleanly
- **THEN** it exits non-zero with `run.changes-conflict`, and standard error names the files, the diff's reference,
  the worktree's path, and how to look at the diff with `troupe diff`

### Requirement: Perform says where a worktree run works
`troupe perform` SHALL show, on standard error before the first event, the workspace of a worktree run with its
path. A rehearsal SHALL show the workspace it would use. When a worktree run's changes are pending at its end, the CLI
SHALL say how to see, accept or discard them.

#### Scenario: The end of a worktree run
- **WHEN** a worktree run ends with changes
- **THEN** standard error names the worktree and the commands `troupe diff`, `troupe accept` and `troupe discard` for
  the run

#### Scenario: Rehearsing a worktree perform
- **WHEN** a person runs `troupe perform tester --rehearse` for an actor whose workspace is `worktree`
- **THEN** it shows workspace `worktree` and the base commit it would use
- **AND** no worktree is made
