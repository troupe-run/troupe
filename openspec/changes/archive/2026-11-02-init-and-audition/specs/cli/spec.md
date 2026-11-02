# Spec Delta

## ADDED Requirements

### Requirement: Init makes a theatre in the current directory
`troupe init` SHALL make `.troupe/` in the working directory, holding a `.gitignore` and a `.gitattributes` with the
patterns troupe keeps in them, and nothing else. It SHALL record no event and define no actor, and SHALL print the
theatre it made and the files it wrote.

#### Scenario: Init in a fresh repository
- **WHEN** a person runs `troupe init` at the root of a git repository with no `.troupe/` in it or above it
- **THEN** `.troupe/.gitignore` holds `local/` and `.*.troupe~`, and `.troupe/.gitattributes` holds
  `events/** -text` and `actors/** -text`
- **AND** `.troupe/` holds nothing else, no event is recorded, and the exit code is 0

#### Scenario: Init in a subdirectory of a repository
- **WHEN** a person runs `troupe init` in `app/` of a git repository with no `.troupe/` in `app/` or above it
- **THEN** the theatre is `app/`, and `app/.troupe/` is made

#### Scenario: Commands find the new theatre
- **WHEN** a person runs `troupe init` and then `troupe status` in the same directory
- **THEN** `troupe status` succeeds, listing no runs, rather than failing with `theatre.not-found`

### Requirement: Init refuses where a theatre already exists
`troupe init` SHALL be refused with `theatre.exists` when the working directory or any directory above it holds
`.troupe`, naming the existing theatre's root and saying to use it. It SHALL change nothing.

#### Scenario: A theatre here
- **WHEN** a person runs `troupe init` in a directory that holds `.troupe/`
- **THEN** it fails with `theatre.exists`, naming that directory
- **AND** nothing in `.troupe/` changes

#### Scenario: A theatre above
- **WHEN** a person runs `troupe init` in `src/` of a project whose root holds `.troupe/`
- **THEN** it fails with `theatre.exists`, naming the project's root
- **AND** no `src/.troupe/` is made

#### Scenario: A file in the way
- **WHEN** a person runs `troupe init` in a directory that holds a file named `.troupe`
- **THEN** it fails with `theatre.exists`, naming the file and saying it isn't a directory
- **AND** the file is unchanged

### Requirement: Init refuses outside a repository
`troupe init` SHALL be refused with `vcs.not-a-repository` when the working directory isn't in a repository of the
theatre's version-control adapter, with a fix that says how to make one. With git, the fix SHALL name `git init`.
troupe SHALL NOT make the repository itself.

#### Scenario: No git repository
- **WHEN** a person runs `troupe init` in a directory that isn't in a git work tree
- **THEN** it fails with `vcs.not-a-repository`, naming the directory, and the fix names `git init`
- **AND** no `.troupe/` and no `.git` are made

#### Scenario: Inside a repository's git directory
- **WHEN** a person runs `troupe init` inside a repository's `.git/` directory
- **THEN** it fails with `vcs.not-a-repository`

### Requirement: Init with an audition defines a working example actor
`troupe init --audition` SHALL make the theatre as `troupe init` does, and SHALL define the example actor `lead` in
the same command. On success it SHALL print the actor, its runner, the files written, and the next steps.

#### Scenario: An audition with the default runner
- **WHEN** a person runs `troupe init --audition` in a fresh git repository
- **THEN** `.troupe/actors/lead.yaml` names the runner `claude-code`, and `.troupe/actors/lead.md` holds its
  character
- **AND** standard output names `lead`, `claude-code` and both files

#### Scenario: Config shows the actor
- **WHEN** a person runs `troupe init --audition` and then `troupe config get actors.lead.runner`
- **THEN** it prints `claude-code`

### Requirement: Init prints the next steps for its audition
After an audition, `troupe init` SHALL print, in order: committing `.troupe/`, allowing the local stage when policy
doesn't already allow it, and `troupe perform lead` with an example `--direction`. For Claude Code it SHALL say that
Claude Code must be installed and logged in.

#### Scenario: Next steps when policy doesn't allow the local stage
- **WHEN** a person runs `troupe init --audition` with `TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE` unset
- **THEN** standard output shows a `git add .troupe` and `git commit` step, then the step that sets
  `TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE=true`, then `troupe perform lead --direction "..."`

#### Scenario: Next steps when policy already allows it
- **WHEN** a person runs `troupe init --audition` with `TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE=true`
- **THEN** standard output shows the commit step and the perform step, and no policy step

#### Scenario: The printed steps work in an empty repository
- **WHEN** a person runs `troupe init --audition --runner scripted` in an empty git repository, then each printed
  step in order, offline
- **THEN** the `troupe perform` it printed ends `succeeded` and exits 0

#### Scenario: The printed steps work with Claude Code
- **WHEN** a person with Claude Code installed and logged in runs `troupe init --audition` in an empty git
  repository, then each printed step in order
- **THEN** the `troupe perform` it printed ends `succeeded` and exits 0

### Requirement: Init's audition runner is named with --runner
`troupe init --audition --runner <runner>` SHALL define the example actor for that runner. Claude Code SHALL be the
runner when `--runner` is absent. A runner troupe doesn't know SHALL be refused with `runner.unknown`, naming the
runners troupe has, before anything is made. `--runner` without `--audition` SHALL be refused as a usage error.

#### Scenario: The scripted runner
- **WHEN** a person runs `troupe init --audition --runner scripted`
- **THEN** `.troupe/actors/lead.yaml` names the runner `scripted`

#### Scenario: A runner troupe doesn't know
- **WHEN** a person runs `troupe init --audition --runner gemini`
- **THEN** it fails with `runner.unknown`, naming `gemini`, `claude-code` and `scripted`
- **AND** no `.troupe/` is made

#### Scenario: A runner without an audition
- **WHEN** a person runs `troupe init --runner scripted`
- **THEN** it exits with the usage-error code, with `usage.missing-argument` naming `troupe init` and `--audition`
- **AND** no `.troupe/` is made

### Requirement: Init can be rehearsed
`troupe init --rehearse`, with or without an audition, SHALL run every check init runs, show the theatre it would
make, the files it would write and, for an audition, the change it would record. It SHALL make, write and record
nothing, and exit with the "would change" code, or with a refusal's own code.

#### Scenario: Rehearsing an audition
- **WHEN** a person runs `troupe init --audition --rehearse` in a fresh git repository
- **THEN** it shows `.troupe/`, its git files, the actor files, and the change's entries for `actors.lead`
- **AND** no `.troupe/` is made, and the exit code is the "would change" code

#### Scenario: Rehearsing where a theatre exists
- **WHEN** a person runs `troupe init --rehearse` in a directory that holds `.troupe/`
- **THEN** it exits with the code of `theatre.exists`

## MODIFIED Requirements

### Requirement: The theatre is found from the working directory
A command that needs a theatre SHALL use the nearest directory, from the working directory upwards, that contains
`.troupe/`. If there is none, it SHALL fail with `theatre.not-found`, naming the directory it searched from, with a
fix that names `troupe init`, and SHALL NOT create one.

#### Scenario: Run from a subdirectory
- **WHEN** a person runs `troupe status` in `src/` of a project whose root holds `.troupe/`
- **THEN** the project's root is the theatre

#### Scenario: No theatre
- **WHEN** a person runs `troupe perform tester ...` in a directory with no `.troupe/` above it
- **THEN** it fails with `theatre.not-found`, naming that directory
- **AND** the fix names `troupe init`
- **AND** no `.troupe/` is created
