# Spec Delta

## MODIFIED Requirements

### Requirement: Perform's exit code follows the run's outcome
`troupe perform` SHALL exit 0 when the run `succeeded` and nothing of it waits at a gate, 4 when it `succeeded` and
its work waits at a gate for a role's answer, 130 when it was `cancelled`, and 1 for every other outcome. A `perform`
refused before the run starts SHALL exit with its error's code.

#### Scenario: Cancelled with Ctrl-C
- **WHEN** a person cancels a run with Ctrl-C
- **THEN** `troupe perform` exits 130, on Linux, macOS and Windows

#### Scenario: A crashed run
- **WHEN** a run ends `crashed`
- **THEN** `troupe perform` exits 1

#### Scenario: Waiting at a gate
- **WHEN** a run of an actor with approvers `[director]` ends `succeeded` with changes
- **THEN** `troupe perform` exits 4, and the exit-code table names 4 as waiting at a gate

#### Scenario: Kept at the gate
- **WHEN** a run with the default approvers ends `succeeded` and `troupe` keeps its changes
- **THEN** `troupe perform` exits 0

### Requirement: Perform says where a worktree run works
`troupe perform` SHALL show, on standard error before the first event, the workspace of a worktree run with its
path. A rehearsal SHALL show the workspace it would use. At a worktree run's end, the CLI SHALL say what became of
its changes: kept at the gate, naming the files and who approved them; waiting at a gate, naming the role and how to
see, approve or reject them; or pending, naming how to see, accept or discard them.

#### Scenario: The end of a worktree run
- **WHEN** a worktree run ends `failed` with changes
- **THEN** standard error names the worktree and the commands `troupe diff`, `troupe accept` and `troupe discard` for
  the run

#### Scenario: The end of a run kept at the gate
- **WHEN** a worktree run ends `succeeded` and `troupe` keeps its changes to `src/a.txt`
- **THEN** standard error says its changes were kept, approved by `troupe`, naming `src/a.txt`

#### Scenario: The end of a run waiting at a gate
- **WHEN** a worktree run's gate raises a cue for `director` after `troupe` passed on a conflict in `src/a.txt`
- **THEN** standard error says the run waits for `director` because `src/a.txt` conflicts, names the worktree, and
  names `troupe diff`, `troupe approve` and `troupe reject` for the run

#### Scenario: Rehearsing a worktree perform
- **WHEN** a person runs `troupe perform tester --rehearse` for an actor whose workspace is `worktree`
- **THEN** it shows workspace `worktree` and the base commit it would use
- **AND** no worktree is made

### Requirement: Init prints the next steps for its audition
After an audition, `troupe init` SHALL print, in order: committing `.troupe/`, allowing the local stage when policy
doesn't already allow it, and `troupe perform lead` with an example `--direction`, whose note says the run waits for the person to approve
or reject it, naming `troupe approve` and `troupe reject`. For Claude Code it SHALL say that
Claude Code must be installed and logged in. The allow step SHALL say to add its line to the shell profile once, naming
the profile for the platform, so that it applies to every theatre the person runs.

#### Scenario: Next steps when policy doesn't allow the local stage
- **WHEN** a person runs `troupe init --audition` with `TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE` unset
- **THEN** standard output shows a `git add .troupe` and `git commit` step, then the step that sets
  `TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE=true`, then `troupe perform lead --direction "..."`

#### Scenario: Next steps when policy already allows it
- **WHEN** a person runs `troupe init --audition` with `TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE=true`
- **THEN** standard output shows the commit step and the perform step, and no policy step

#### Scenario: The allow step says to set it once, in the shell profile
- **WHEN** a person on Linux or macOS runs `troupe init --audition` with `TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE`
  unset
- **THEN** the allow step's note names `~/.zshrc` and `~/.bashrc`, says to add the line once, and that it then applies
  to every theatre
- **AND** it doesn't say to set it in each shell

#### Scenario: The allow step on Windows names the PowerShell profile
- **WHEN** a person on Windows runs `troupe init --audition` with `TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE` unset
- **THEN** the allow step's line is the `$env:` form, and its note names the PowerShell profile (`$PROFILE`)

#### Scenario: The printed steps work in an empty repository
- **WHEN** a person runs `troupe init --audition --runner scripted` in an empty git repository, then each printed
  step in order, offline
- **THEN** the `troupe perform` it printed ends `succeeded`, waits at a gate for `director`, and exits 4

#### Scenario: The printed steps work with Claude Code
- **WHEN** a person with Claude Code installed and logged in runs `troupe init --audition` in an empty git
  repository, then each printed step in order
- **THEN** the `troupe perform` it printed ends `succeeded`, waits at a gate for `director`, and exits 4

#### Scenario: The perform step names the gate
- **WHEN** a person runs `troupe init --audition`
- **THEN** the perform step's note names `troupe diff`, `troupe approve` and `troupe reject`, and doesn't name
  `troupe accept`

## ADDED Requirements

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
