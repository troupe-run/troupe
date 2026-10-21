# Spec Delta

## ADDED Requirements

### Requirement: A run uses the actor as config defines it
`perform` SHALL take the actor's runner, options, effect check and character from the merged config, as it is when
the run starts. A request SHALL name only the actor, the direction and whether to rehearse.

#### Scenario: The character reaches the runner
- **WHEN** config gives `tester` a character, and a person performs `tester` with the scripted runner and a script
  that checks the character it receives
- **THEN** the run succeeds, because the runner received exactly that character

#### Scenario: Config changed between two runs
- **WHEN** a person performs `tester`, changes its runner's options, and performs it again
- **THEN** the second run uses the new options

## MODIFIED Requirements

### Requirement: What a run was asked to do is kept
The run's start SHALL record the actor's name, the runner requested, the effect check, and the config version it ran
with: the sorted ids of the config stream's heads that the merged config was worked out from. The direction SHALL be
stored as an artifact, and the run's start SHALL reference it by hash.

#### Scenario: The config a run used
- **WHEN** a run is performed, and the actor's options are changed afterwards
- **THEN** the run's start names the config version from before the change
- **AND** working out config at that version gives the options the run used

#### Scenario: Options are referenced, not inlined
- **WHEN** a run is performed for an actor whose options hold an inline script
- **THEN** no event in the run's stream holds the script itself
- **AND** the run's start references the options through its config version, not as an artifact of their own

#### Scenario: The direction is referenced, not inlined
- **WHEN** a run is performed with a direction
- **THEN** the run's start holds a `sha256:` reference whose artifact is that direction, byte for byte
- **AND** no event in the run's stream holds the direction itself
