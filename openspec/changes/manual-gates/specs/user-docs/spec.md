# Spec Delta

## MODIFIED Requirements

### Requirement: The first run leads with Claude Code and your own direction
The first-run walkthrough SHALL start from `troupe init --audition` in the reader's own repository, have them set the
`lead` actor's character from a file of their own with `troupe config set`, and run `troupe perform lead` with a
`--direction` they type. Each command it gives SHALL run as written in the docs check, with a stand-in `claude`.

#### Scenario: The Claude Code walkthrough runs as written
- **WHEN** the docs check runs each command the walkthrough gives, in order, in a git repository with a commit, with a
  stand-in `claude` on the path
- **THEN** `troupe init --audition` exits 0, and the `troupe perform lead --direction "..."` it gives prints
  `run <id> succeeded` and exits 4, waiting at a gate for `director`
- **AND** the `troupe diff`, `troupe approve`, `troupe status` and `troupe logs` it gives each exit 0 for that run

#### Scenario: The walkthrough's steps are the ones init prints
- **WHEN** the docs check compares the walkthrough's commit and allow commands with what `troupe init --audition`
  prints
- **THEN** they are the same commands

### Requirement: The first run has an offline path with the scripted runner
The first-run walkthrough SHALL give a way to try troupe with no account and no network: `troupe init --audition
--runner scripted` in a new repository, then the same steps. Each command it gives SHALL run as written in the docs
check, with no `claude` on the path.

#### Scenario: The offline walkthrough runs as written
- **WHEN** the docs check runs each command of the offline path, in order, in a new git repository with no `claude`
  on the path
- **THEN** its `troupe perform lead` prints `run <id> succeeded` and exits 4, waiting at a gate for `director`

### Requirement: The glossary is the single source of troupe's vocabulary
`docs/prompt-book/glossary.md` SHALL hold one table row per term, each term in plain text. It SHALL have rows for
stage, rehearsal, audition, system, cue and approver, and cue's meaning SHALL mark it as provisional. The glossary and the
house's page SHALL NOT call the house's name unconfirmed ("TBC", "isn't final").

#### Scenario: A term in code font
- **WHEN** a glossary row's term is written `` `system` ``
- **THEN** the docs check fails, naming the row, and says to write the term plainly and name any literal in its
  meaning

#### Scenario: A missing term
- **WHEN** the glossary has no row for rehearsal
- **THEN** the docs check fails, naming rehearsal

#### Scenario: No audition row
- **WHEN** the glossary has no row for audition
- **THEN** the docs check fails, naming audition

#### Scenario: A duplicate term
- **WHEN** the glossary has two rows for audition, at different places in the table
- **THEN** the docs check fails once, naming audition and that it has 2 rows, and says to keep one

#### Scenario: A duplicate that differs only in case or spacing
- **WHEN** the glossary has a row for "the house" and another for "The  House"
- **THEN** the docs check fails, naming the term as the first row writes it, and that it has 2 rows

#### Scenario: No approver row
- **WHEN** the glossary has no row for approver
- **THEN** the docs check fails, naming approver

## ADDED Requirements

### Requirement: The first run answers its gate and says how to drop the wait
The first-run walkthrough SHALL have the reader see the run's diff and answer its gate with `troupe approve`, saying
`troupe reject` throws the work away. It SHALL then say that an actor with no approvers set keeps clean work without
waiting, and how to drop the wait: unset `actors.lead.approvers`. Its commands SHALL run as written in the docs check.

#### Scenario: The walkthrough approves
- **WHEN** a reader reads the first-run walkthrough's section on keeping the run's work
- **THEN** it gives `troupe diff <run>` and `troupe approve <run>`, names `troupe reject <run>`, and doesn't give
  `troupe accept`

#### Scenario: Dropping the wait runs as written
- **WHEN** the docs check runs the walkthrough's command to drop the wait, then performs `lead` again with a direction
  whose changes apply cleanly
- **THEN** the command exits 0, and the second `troupe perform lead` keeps its changes, approved by `troupe`, and
  exits 0
