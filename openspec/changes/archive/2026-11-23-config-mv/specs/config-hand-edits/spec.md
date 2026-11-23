## MODIFIED Requirements

### Requirement: Adding or deleting a file adds or removes what it held
A config file that config doesn't hold SHALL be read as adding what it holds. A config file this clone had at its
last sync, and that's gone, SHALL be read as removing what it held: an actor's `.md` file its character, and its
`.yaml` and `.md` files together the actor. A missing file this clone never had SHALL be written again from config,
never read as a removal.

#### Scenario: A new actor
- **WHEN** a person writes `.troupe/actors/qa.yaml` with a runner and an effect check, and runs `troupe sync`
- **THEN** one change adds the actor `qa`

#### Scenario: A deleted character
- **WHEN** a person deletes `.troupe/actors/tester.md` and runs `troupe sync`
- **THEN** one change removes `actors.tester.character`, and the file isn't written again

#### Scenario: A deleted actor
- **WHEN** a person deletes `.troupe/actors/tester.yaml` and `.troupe/actors/tester.md`, and runs `troupe sync`
- **THEN** one change removes the group `actors.tester`

#### Scenario: A character left without its actor
- **WHEN** a person deletes `.troupe/actors/tester.yaml` but not `.troupe/actors/tester.md`, and runs `troupe sync`
- **THEN** it is refused with `config.file-invalid`, saying the actor needs its `.yaml` file and that deleting both
  files removes the actor
- **AND** when another actor's `.yaml` file arrived in the same sweep, the fix also says to move the `.md` file with
  it, or to rename with `troupe config mv`
- **AND** nothing is recorded

#### Scenario: A file this clone never had is written, not removed
- **WHEN** a clone's config has the actor `tester`, its files were never committed, and a person runs `troupe sync`
- **THEN** `.troupe/actors/tester.yaml` and `.troupe/actors/tester.md` are written from config, each with a
  `config.file-rewritten` notice, and nothing is recorded

#### Scenario: The record of the files this clone had is missing or unreadable
- **WHEN** troupe's record of the config files this clone had is gone or can't be read, `.troupe/actors/tester.md`
  is missing, and a person runs `troupe sync`
- **THEN** the file is written again from config, never read as removing the character
- **AND** when the record couldn't be read, a `config.present-unreadable` notice names it

#### Scenario: A file a git pull deleted
- **WHEN** this clone had `.troupe/actors/tester.md` at its last sync, a `git pull` deletes it with no change to
  config from the other side, and a person runs `troupe sync`
- **THEN** a change by the `unknown` actor removes `actors.tester.character`
- **AND** its `config.hand-edit-recorded` notice says it was recorded from the file going missing

#### Scenario: A runtime file deleted
- **WHEN** config sets `runtimes.openai.model`, and a person deletes `.troupe/runtimes/openai.yaml` and runs `troupe
  sync`
- **THEN** one change removes the group `runtimes.openai`

## ADDED Requirements

### Requirement: A hand move with the same values is a rename
When one sweep reads an entity's files as gone (files this clone had at its last sync) and another entity's files of
the same kind as new, and the new entity's values equal the gone one's, it SHALL record one change by the unknown
author renaming the gone entity to the new one, not a removal and an addition. Values SHALL be compared as values.

#### Scenario: An actor moved by hand
- **WHEN** a person runs `git mv .troupe/actors/tester.yaml .troupe/actors/qa.yaml` and the same for `tester.md`,
  then runs `troupe sync`
- **THEN** one change by the `unknown` actor renames `actors.tester` to `actors.qa`, its lineage's `vcs.source` names
  `.troupe/actors/qa.yaml`, and a `config.hand-move-recorded` notice names both names
- **AND** no file is written

#### Scenario: Formatting doesn't count
- **WHEN** a person moves `tester`'s files to `qa`'s names and, in `qa.yaml`, changes a comment, the order of keys and
  the quoting of a string, and drops the `$schema` line
- **THEN** the sweep records the rename, and nothing else

#### Scenario: A runtime moved by hand carries its actors
- **WHEN** `tester` has `runtime: gpu-box`, and a person moves `.troupe/runtimes/gpu-box.yaml` to
  `.troupe/runtimes/gpu.yaml` and runs `troupe sync`
- **THEN** one change by the `unknown` actor renames the runtime and sets `actors.tester.runtime` to `gpu`
- **AND** `.troupe/actors/tester.yaml` is written back with only its `runtime` line changed

#### Scenario: A built-in runtime's file moved
- **WHEN** config sets `runtimes.ollama.model`, and a person moves `.troupe/runtimes/ollama.yaml` to
  `.troupe/runtimes/gpu.yaml`
- **THEN** the sweep records removing `runtimes.ollama` and adding `runtimes.gpu`, and a `config.move-not-detected`
  notice says a built-in runtime's name is never renamed

#### Scenario: Moved and moved back before a sweep
- **WHEN** a person moves `tester`'s files to `qa`'s names and back, then runs `troupe sync`
- **THEN** nothing is recorded

#### Scenario: Moved back after a sweep
- **WHEN** a sweep has recorded `tester` renamed to `qa`, and the person moves the files back to `tester`'s names and
  runs `troupe sync`
- **THEN** one change by the `unknown` actor renames `qa` to `tester`

### Requirement: A hand move with different values is a removal and an addition
When a sweep reads an entity's files as gone and another's of the same kind as new, but their values differ, it SHALL
record removing one and adding the other, as for any deleted and added files, and SHALL say so with a
`config.move-not-detected` notice naming both and `troupe config mv` as the way to keep the history.

#### Scenario: Moved and edited at once
- **WHEN** a person moves `tester`'s files to `qa`'s names and changes the runner in `qa.yaml`, then runs `troupe sync`
- **THEN** the sweep records removing `actors.tester` and adding `actors.qa`
- **AND** a `config.move-not-detected` notice names both, and says to move without editing, or use `troupe config
  mv`, then edit

### Requirement: An ambiguous hand move is refused
When the values of a gone entity equal more than one new entity's, or a new entity's equal more than one gone
entity's, the sweep SHALL be refused with `config.move-ambiguous`, recording nothing. It SHALL name every file
involved, and its fix SHALL name `troupe config mv` for each rename meant.

#### Scenario: Two identical actors moved
- **WHEN** actors `a` and `b` have equal values, and a person moves `a`'s files to `x`'s names and `b`'s to `y`'s
- **THEN** the sweep is refused with `config.move-ambiguous`, naming the four `.yaml` files, and nothing is recorded

#### Scenario: One actor copied to two names
- **WHEN** a person copies `tester`'s files to `qa`'s and `qa2`'s names and deletes `tester`'s
- **THEN** the sweep is refused with `config.move-ambiguous`

### Requirement: Config mv on files already moved records the rename
When a person runs `troupe config mv <kind>.<old> <kind>.<new>` after moving the old entity's files to the new names
by hand, it SHALL record the rename as the person's change and write no file. Then the sweep SHALL read the moved
files against the renamed entity, and the remaining files as usual.

#### Scenario: The way out of an ambiguous move
- **WHEN** actors `a` and `b` have equal values, a person has moved `a`'s files to `x`'s names and `b`'s to `y`'s, and
  runs `troupe config mv actors.a actors.x`
- **THEN** the person's change renames `a` to `x`, and a change by the `unknown` actor renames `b` to `y`
- **AND** no file is written

#### Scenario: Moved and edited, then config mv
- **WHEN** a person has moved `tester`'s files to `qa`'s names and changed the runner in `qa.yaml`, and runs `troupe
  config mv actors.tester actors.qa`
- **THEN** the person's change renames `tester` to `qa`, and then a change by the `unknown` actor sets
  `actors.qa.runner`
