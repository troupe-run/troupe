# Spec Delta

## MODIFIED Requirements

### Requirement: A run uses the actor as config defines it
`perform` SHALL take the actor's runner, options, effects, effect check and character from the merged config, as it
is when the run starts. A request SHALL name only the actor, the direction and whether to rehearse.

#### Scenario: The character reaches the runner
- **WHEN** config gives `tester` a character, and a person performs `tester` with the scripted runner and a script
  that checks the character it receives
- **THEN** the run succeeds, because the runner received exactly that character

#### Scenario: Config changed between two runs
- **WHEN** a person performs `tester`, changes its runner's options, and performs it again
- **THEN** the second run uses the new options

#### Scenario: The effects reach the runner
- **WHEN** config gives `tester` `effects.write: ["out/**"]` and a person performs it
- **THEN** the runner's `run/start` carries `write: ["out/**"]` and empty `delete` and `move`

## ADDED Requirements

### Requirement: Perform's effects check shows the declaration
`perform` SHALL show the effects the run starts with, and, when the effect check fails because of the audit, show
each change outside the declaration with the effect it needed, on every surface, as structured data.

#### Scenario: A failed audit on the command line
- **WHEN** a run fails its audit for `src/a.py`
- **THEN** `troupe perform` reports the outcome `failed`, naming `src/a.py`, `write`, and the `troupe config set` that
  would declare it
