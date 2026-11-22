## ADDED Requirements

### Requirement: Config is worked out only from its events
troupe SHALL work out config only from the theatre's config events. A config file's content SHALL change config only
through the change the sweep records from it (spec: config-hand-edits), never by being read in place of the events.

#### Scenario: A hand edit changes config through the change it records
- **WHEN** a person changes `runner` in `.troupe/actors/tester.yaml` by hand, and runs `troupe config get
  actors.tester.runner`
- **THEN** it shows the edited runner
- **AND** a `Config.Changed` setting `actors.tester.runner` was recorded, so a clone that has the events and not the
  file works out the same config

## MODIFIED Requirements

### Requirement: A command records one change
Each command that changes config SHALL record exactly one `Config.Changed` event for its own change, however many
values it changes. Separate commands SHALL NOT be combined into one event. A command that would change nothing SHALL
record nothing and say so. The sweep before a command records its own changes (spec: config-hand-edits).

#### Scenario: Several values in one command
- **WHEN** a person runs `troupe config set actors.tester.runner=scripted actors.tester.expect='["out/hello.txt"]'`
- **THEN** one `Config.Changed` is recorded, with an entry for each of the two values

#### Scenario: Two commands in a row
- **WHEN** a person runs `troupe config set` twice, with nothing in between
- **THEN** two `Config.Changed` events are recorded, each with its own change id and lineage

#### Scenario: Setting a value to what it already is
- **WHEN** a person sets `actors.tester.runner` to the runner it already has
- **THEN** nothing is recorded, and the command says nothing changed

### Requirement: Any conflict blocks config
While config has any conflict, every command that uses config SHALL refuse with `config.conflict`, listing each
conflict and the fix, except `config get` and a command whose changes, its sweep's included, resolve every conflict.

#### Scenario: Perform with a conflict elsewhere
- **WHEN** config has a conflict on `tester` and a person runs `troupe perform reviewer`
- **THEN** it is refused with `config.conflict`, naming the conflict on `tester`

#### Scenario: Config get shows the conflict
- **WHEN** config has a conflict and a person runs `troupe config get`
- **THEN** it shows the config with each conflict and both sides' changes

### Requirement: A change resolves conflicts by setting every conflicting value
The changes one command records while config has conflicts, its sweep's and its own, SHALL be accepted only if
together they set or unset every conflicting value, and SHALL be accepted when they change other values too. Changes
that leave a conflict SHALL be refused, naming what's left.

#### Scenario: Resolving a window
- **WHEN** a person resolves a conflict on `min` with `troupe config set …min=4 …max=14`
- **THEN** the change is recorded, config has no conflict, and lineage records who resolved it

#### Scenario: A change that resolves nothing
- **WHEN** config has a conflict on `tester` and a person sets a value of `reviewer` only
- **THEN** it is refused with `config.conflict`, naming the conflict left

## REMOVED Requirements

### Requirement: Config is read only from its events
**Reason**: a hand edit now changes config, through the change the sweep records from the file (#119), so the
scenario "A file edited by hand doesn't change config" no longer holds.
**Migration**: "Config is worked out only from its events" keeps the rule that config comes only from events.
