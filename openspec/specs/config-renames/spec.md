# config-renames Specification

## Purpose
Capability: `cap:config`

Renaming an actor or a runtime as one change, with `troupe config mv` or by moving its files, so that its history,
the runs recorded under its old name and changes made to it on other branches all follow it to the new name.

## Requirements

### Requirement: A rename is one entry naming the old name
`troupe config mv` SHALL record one `Config.Changed` whose entry has `path` set to the new name, `renamedFrom` set to
the old name, `before` set to the hash of the whole group it moves, and no `after`. Afterwards config SHALL hold the
group's values under the new name and nothing under the old one. Events recorded before the rename SHALL be left
exactly as they were.

#### Scenario: Renaming an actor
- **WHEN** config has the actor `tester` and a person runs `troupe config mv actors.tester actors.qa`
- **THEN** one `Config.Changed` is recorded with the entry `{"path": ["actors", "qa"], "renamedFrom": ["actors",
  "tester"], "before": <hash of tester's group>}`
- **AND** `troupe config get actors.qa` shows every value `tester` had, and `troupe config get actors.tester` shows
  nothing

#### Scenario: Renaming a runtime
- **WHEN** config has the runtime `gpu-box` and no actor names it, and a person runs `troupe config mv runtimes.gpu-box
  runtimes.gpu`
- **THEN** one change renames the runtime, and config holds its values under `runtimes.gpu`

#### Scenario: Earlier events don't change
- **WHEN** an actor is renamed
- **THEN** every event recorded before the rename reads byte for byte as it did

### Requirement: A runtime's rename carries the actors that name it
When a runtime is renamed, the same change SHALL set `runtime` to the new name on every actor that names the old
one, each as an ordinary entry.

#### Scenario: Two actors on a renamed runtime
- **WHEN** actors `tester` and `reviewer` have `runtime: gpu-box`, and a person runs `troupe config mv runtimes.gpu-box
  runtimes.gpu`
- **THEN** one change holds the rename entry and entries setting `actors.reviewer.runtime` and `actors.tester.runtime`
  to `gpu`

### Requirement: Only a whole actor or runtime can be renamed
`config mv` SHALL be refused, recording nothing, with `config.move-not-entity`, when either path isn't
`actors.<name>` or `runtimes.<name>`, or the two paths are of different kinds. The new name SHALL be checked like any
name of its kind.

#### Scenario: A value path
- **WHEN** a person runs `troupe config mv actors.tester.runner actors.tester.model`
- **THEN** it is refused with `config.move-not-entity`, saying only a whole actor or runtime can be renamed

#### Scenario: Across kinds
- **WHEN** a person runs `troupe config mv actors.tester runtimes.tester`
- **THEN** it is refused with `config.move-not-entity`, saying a rename keeps its kind

#### Scenario: An invalid new name
- **WHEN** a person runs `troupe config mv actors.tester actors.Q_A`
- **THEN** it is refused, naming the rule for an actor's name, and nothing is recorded

### Requirement: A rename needs its source and refuses an existing target
`config mv` SHALL be refused, recording nothing, with `config.move-source-missing` when config has nothing at the old
name, and with `config.move-target-exists` when config already holds the new name. There SHALL be no option that
overwrites the target.

#### Scenario: No such actor
- **WHEN** config has no actor `ghost` and a person runs `troupe config mv actors.ghost actors.qa`
- **THEN** it is refused with `config.move-source-missing`

#### Scenario: The target exists
- **WHEN** config has actors `tester` and `qa`, and a person runs `troupe config mv actors.tester actors.qa`
- **THEN** it is refused with `config.move-target-exists`, naming `actors.qa`, and both actors are unchanged

### Requirement: A built-in runtime's name is never renamed to or from
`config mv` SHALL be refused, recording nothing, with `config.move-built-in` when either name is one of troupe's
built-in runtimes, since a runtime in config with a built-in's name holds overrides of the built-in, not a runtime of
its own.

#### Scenario: Renaming a built-in's overrides
- **WHEN** config sets `runtimes.ollama.model`, and a person runs `troupe config mv runtimes.ollama runtimes.gpu`
- **THEN** it is refused with `config.move-built-in`, naming `ollama` as a built-in runtime

#### Scenario: Renaming onto a built-in's name
- **WHEN** a person runs `troupe config mv runtimes.gpu-box runtimes.openai`
- **THEN** it is refused with `config.move-built-in`

### Requirement: A change on another line follows a rename
When lines of history are merged, a change one line makes to an entity under its old name SHALL apply to the entity
under the name another line renamed it to, with no conflict. A history with no renames SHALL merge exactly as it did
before renames existed.

#### Scenario: A character set on a branch that didn't rename
- **WHEN** one branch renames `tester` to `qa`, another sets `actors.tester.character`, and they are merged
- **THEN** config holds that character at `actors.qa.character`, has no `actors.tester`, and has no conflict

#### Scenario: A rename and a rename back
- **WHEN** one branch renames `tester` to `qa` and back to `tester`, another sets `actors.tester.runner`, and they are
  merged
- **THEN** config holds that runner at `actors.tester.runner`, with no conflict

#### Scenario: Every clone agrees on a rename
- **WHEN** the same branches' events, renames among them, reach two clones in different orders
- **THEN** both clones work out the same config and the same conflicts

#### Scenario: A history with no renames
- **WHEN** a history holds no rename entry
- **THEN** config and conflicts are what they were before renames existed

### Requirement: A name after a rename is a new entity
A change made after a rename, on a line that holds the rename, to the old name SHALL make or change a new entity of
that name, and SHALL NOT follow the rename.

#### Scenario: A new tester after the rename
- **WHEN** a person renames `tester` to `qa`, then sets `actors.tester.runner=scripted` and `actors.tester.expect=[]`
- **THEN** config has both `qa`, with the old values, and a new `tester`

#### Scenario: A concurrent change still follows
- **WHEN** one branch renames `tester` to `qa` and then makes a new `tester`, another branch sets the old
  `tester`'s character, and they are merged
- **THEN** the character lands on `qa`, and the new `tester` is unchanged

### Requirement: Renames that can't both hold are a conflict
Two lines renaming one entity to different names, one renaming an entity while the other removes it, or one renaming
an entity onto a name the other made SHALL be a conflict between the changes, shown and resolved like any other.

#### Scenario: Two renames
- **WHEN** one branch renames `tester` to `qa`, another renames it to `reviewer`, and they are merged
- **THEN** the two changes are in conflict on `actors.tester`, and config shows `tester` under its name from before
  the split

#### Scenario: The same rename on both branches
- **WHEN** two branches each rename `tester` to `qa`, and they are merged
- **THEN** config has `qa`, with no conflict

#### Scenario: A rename and a removal
- **WHEN** one branch renames `tester` to `qa`, another removes `tester`, and they are merged
- **THEN** the two changes are in conflict

#### Scenario: A rename onto a name made on another branch
- **WHEN** one branch renames `tester` to `qa`, another makes a new actor `qa`, and they are merged
- **THEN** the rename and the changes that made the other `qa` are in conflict on `actors.qa`

#### Scenario: Resolving two renames with a rename
- **WHEN** config has the conflict of two renames of `tester`, and a person runs `troupe config mv actors.tester
  actors.qa`
- **THEN** the change is recorded, and config has `qa` and no conflict
