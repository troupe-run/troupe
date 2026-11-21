## ADDED Requirements

### Requirement: Config and sync commands
The CLI SHALL offer `troupe config set`, `troupe config unset`, `troupe config get` and `troupe sync`, each calling the
core through the client protocol. `troupe config get` SHALL take `--json`, which writes the query's result exactly in
its protocol shape. There SHALL be no `troupe flush`.

#### Scenario: Config get as JSON
- **WHEN** a person runs `troupe config get --json`
- **THEN** standard output is one JSON document that validates against the `config-get` result schema

#### Scenario: Flush is gone
- **WHEN** a person runs `troupe flush`
- **THEN** it is refused as an unknown command

### Requirement: An audition defines a working example actor
`troupe init --audition` SHALL make the theatre as `troupe init` does, and SHALL define the example actor `lead` in
the same command. On success it SHALL print the actor, its runner, the files written, and the next steps. When the
actor has a character, it SHALL say to change it by editing `.troupe/actors/lead.md`.

#### Scenario: An audition with the default runner
- **WHEN** a person runs `troupe init --audition` in a fresh git repository
- **THEN** `.troupe/actors/lead.yaml` names the runner `claude-code`, and `.troupe/actors/lead.md` holds its
  character
- **AND** standard output names `lead`, `claude-code` and both files

#### Scenario: Config shows the actor
- **WHEN** a person runs `troupe init --audition` and then `troupe config get actors.lead.runner`
- **THEN** it prints `claude-code`

#### Scenario: The character is changed by editing its file
- **WHEN** a person runs `troupe init --audition`, writes text of their own into the `.troupe/actors/lead.md` it
  names, then runs `troupe perform lead --rehearse`
- **THEN** the rehearsal isn't refused, and `troupe config get actors.lead.character` prints the file's text

## MODIFIED Requirements

### Requirement: A rehearsal's exit code says what it found
A rehearsal SHALL exit 0 when the command would succeed with nothing to do, with the exit code for "would change"
when it would succeed and change something, and with the refusal's own code when it would be refused.

#### Scenario: Files that are out of date
- **WHEN** a person runs `troupe sync --rehearse` and a config file isn't what config would write
- **THEN** it exits with the "would change" code, naming the file

#### Scenario: Files in line
- **WHEN** every config file says what config says
- **THEN** `troupe sync --rehearse` exits 0

#### Scenario: A rehearsal that would be refused
- **WHEN** a config file was left invalid by hand and a person runs `troupe sync --rehearse`
- **THEN** it exits with the code of `config.file-invalid`, naming the file

## REMOVED Requirements

### Requirement: Config and flush commands
**Reason**: `troupe sync` replaces `troupe flush`, with no alias (owner, 2026-11-21).
**Migration**: "Config and sync commands". Run `troupe sync` where `troupe flush` was run.

### Requirement: Init with an audition defines a working example actor
**Reason**: once hand edits are read back, the audition says to edit the character's file, not to use `troupe config
set` (the owner's comment on #119), so the scenario "The character is changed through config" no longer holds.
**Migration**: "An audition defines a working example actor", with the scenario "The character is changed by editing
its file".
