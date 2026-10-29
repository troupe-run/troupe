# config Specification

## Purpose

Capability: `cap:config`

Holds a theatre's config as events with lineage, works out the config every command uses from them, including
across merged branches, and defines the actor, the first kind of config.

## Requirements

### Requirement: Config is read only from its events
troupe SHALL work out config only from the theatre's config events. It SHALL NOT read a config file's content to
decide what config holds.

#### Scenario: A file edited by hand doesn't change config
- **WHEN** a person changes `runner` in `.troupe/actors/tester.yaml` by hand, and runs `troupe config get
  actors.tester.runner`
- **THEN** it shows the runner the config events set
- **AND** the edited file is refused when it is next flushed

### Requirement: One stream per theatre
A theatre's config events SHALL be one stream, with the same id in every theatre.

#### Scenario: Two actors share one stream
- **WHEN** a person sets a value of `tester` and then a value of `reviewer`
- **THEN** both changes are events in the same stream, the second following the first

### Requirement: A command records one change
Each command that changes config SHALL record exactly one `Config.Changed` event, however many values it changes.
Separate commands SHALL NOT be combined into one event. A command that would change nothing SHALL record nothing
and say so.

#### Scenario: Several values in one command
- **WHEN** a person runs `troupe config set actors.tester.runner=scripted actors.tester.expect='["out/hello.txt"]'`
- **THEN** one `Config.Changed` is recorded, with an entry for each of the two values

#### Scenario: Two commands in a row
- **WHEN** a person runs `troupe config set` twice, with nothing in between
- **THEN** two `Config.Changed` events are recorded, each with its own change id and lineage

#### Scenario: Setting a value to what it already is
- **WHEN** a person sets `actors.tester.runner` to the runner it already has
- **THEN** nothing is recorded, and the command says nothing changed

### Requirement: A change entry holds the path, the old value's hash and the new value
Each entry in a `Config.Changed` SHALL hold the value's path as an array of keys, `before` as `sha256:` and the
SHA-256 of the old value's canonical JSON, and `after` as the new value. `before` SHALL be absent when the value
didn't exist, and `after` absent when it was removed. Neither SHALL be null.

#### Scenario: A changed value
- **WHEN** `actors.tester.runner` changes from `scripted` to `claude-code`
- **THEN** the entry's path is `["actors", "tester", "runner"]`, its `before` is the hash of `"scripted"`, and its
  `after` is `"claude-code"`

#### Scenario: A new value
- **WHEN** `actors.tester.character` is set for the first time
- **THEN** its entry has an `after` and no `before`

#### Scenario: The same canonical form as event ids
- **WHEN** a value's `before` is compared with the hash of the value as recorded in an earlier `after`
- **THEN** they are equal, for strings, numbers, booleans and arrays alike

### Requirement: Objects are groups, and every other value is whole
An object in config SHALL be a group of values, and a path into it SHALL name one of its values. A string, number,
boolean or array SHALL be one value, replaced and compared as a whole, never merged inside (#135). An entry's
`after` SHALL never be an object.

#### Scenario: Setting a value inside a group
- **WHEN** a person sets `actors.tester.options.script` to a list of steps
- **THEN** the change has one entry, for the path `["actors", "tester", "options", "script"]`, whose `after` is the
  whole list

#### Scenario: A value that is an object
- **WHEN** a person tries to set `actors.tester.runner` to a JSON object
- **THEN** it is refused, naming the path and saying an object is a group of values

### Requirement: A group is removed as one entry
Removing a group SHALL be one entry addressed to the group, whose `before` is the hash of the group's canonical JSON
and which has no `after`.

#### Scenario: Removing an actor
- **WHEN** a person runs `troupe config unset actors.tester`
- **THEN** one change is recorded, with one entry for the path `["actors", "tester"]` and no `after`
- **AND** `tester` is no longer in config

### Requirement: A group can be set whole from a file
Setting a group from a file SHALL replace the whole group in one change, with an entry for each value added, changed
or removed under it.

#### Scenario: Setting an actor from a file
- **WHEN** `tester` has `runner` and `options`, and a person sets `actors.tester` from a file holding `runner` and
  `expect`
- **THEN** one change is recorded, setting `expect`, setting `runner` if it differs, and removing `options`

### Requirement: Values are checked before a change is recorded
A change SHALL be refused, recording nothing, when the config it would make fails its kind's schema or, for an
actor, when its options fail its runner's published options schema. The error SHALL name the path and the rule.

#### Scenario: A misspelt field
- **WHEN** a person sets `actors.tester.runnr`
- **THEN** it is refused, naming the path and saying the actor has no such field
- **AND** nothing is recorded

#### Scenario: Options the runner doesn't define
- **WHEN** a person sets `actors.tester.options.speed` for the scripted runner
- **THEN** it is refused, naming the path and the scripted runner's options schema

### Requirement: A merge combines each line's net change
When the config stream has more than one head, config SHALL be worked out from both lines of history: for each
value, each line's net change since the lines split, from its first `before` to its last `after`. A line whose net
change ends where it began SHALL count as not changing the value. A line whose first changes to the value start from
different values SHALL count as changing it.

#### Scenario: Two branches change different actors
- **WHEN** one branch sets a value of `reviewer`, another sets a value of `tester`, and they are merged
- **THEN** config holds both changes, with no conflict

#### Scenario: A change and a change back
- **WHEN** one branch changes `tester`'s character and changes it back, another changes it to new text, and they
  are merged
- **THEN** config holds the new text, with no conflict

#### Scenario: Two branches make the same change
- **WHEN** two branches each set `actors.tester.runner` to `claude-code`, and are merged
- **THEN** config holds `claude-code`, with no conflict

#### Scenario: Every clone agrees
- **WHEN** the same branches' events reach two clones in different orders
- **THEN** both clones work out the same config and the same conflicts

#### Scenario: A line whose first changes start from different values is a change
- **WHEN** one branch changes `tester`'s character from new text to other text, and another line of history holds two
  concurrent changes to it, one from that new text and one from another value, which a settle joins, and the line
  ends at the new text
- **THEN** the two lines are in conflict, whatever order the events arrived in

### Requirement: The history before the lines works out a value no line's change is left at
Where no line's change is left at a value, because the lines conflict or every one counts as not changing it, the
history before those lines SHALL work the value out by the same rule, never the order the events arrived in.

#### Scenario: A conflict after a settle shows the value the settle left
- **WHEN** two branches set `tester`'s character, one changing it to new text and the other changing it to other text
  and back, a write settles them, and two branches from the settle then set it to different text
- **THEN** the two later changes are in conflict, and config shows the new text the settle left, whatever order the
  events arrived in

#### Scenario: Lines after a settle that change a value back leave the value the settle left
- **WHEN** two branches set `tester`'s character, one changing it to new text and the other changing it to other text
  and back, a write settles them, and two branches from the settle each change it and change it back
- **THEN** config holds the new text the settle left, with no conflict, whatever order the events arrived in

### Requirement: Differing net changes to a value are a conflict between whole changes
Two lines whose net changes set one value to different things SHALL be in conflict. A conflict SHALL name each
conflicting change whole: its change id, who made it, when, and every entry in it.

#### Scenario: A window moved on one branch and narrowed on another
- **WHEN** one branch's change sets `min` from 0 to 5 and `max` from 10 to 15, another's sets `min` from 0 to 2, and
  they are merged
- **THEN** the two changes are in conflict
- **AND** the conflict shows both changes whole, including the first change's `max`

#### Scenario: A group removed on one branch and changed on another
- **WHEN** one branch removes `tester` and another changes `tester`'s character, and they are merged
- **THEN** the two changes are in conflict

### Requirement: A merged config that fails validation is a conflict
When the merged config fails its kind's schema, or an actor's options fail its runner's options schema, the changes
since the split that touched what failed SHALL be in conflict, even when no single value conflicts.

#### Scenario: Options that no longer suit the runner
- **WHEN** one branch changes `tester`'s runner, another changes options that only the old runner defines, and they
  are merged
- **THEN** the two changes are in conflict, naming the actor and the options schema it fails

### Requirement: Any conflict blocks config
While config has any conflict, every command that uses config SHALL refuse with `config.conflict`, listing each
conflict and the fix, except `config get` and a change that resolves every conflict.

#### Scenario: Perform with a conflict elsewhere
- **WHEN** config has a conflict on `tester` and a person runs `troupe perform reviewer`
- **THEN** it is refused with `config.conflict`, naming the conflict on `tester`

#### Scenario: Config get shows the conflict
- **WHEN** config has a conflict and a person runs `troupe config get`
- **THEN** it shows the config with each conflict and both sides' changes

### Requirement: A change resolves conflicts by setting every conflicting value
A change recorded while config has conflicts SHALL be accepted only if it sets or unsets every conflicting value, and SHALL
be accepted when it changes other values too. One that leaves a conflict SHALL be refused, naming what's left.

#### Scenario: Resolving a window
- **WHEN** a person resolves a conflict on `min` with `troupe config set …min=4 …max=14`
- **THEN** the change is recorded, config has no conflict, and lineage records who resolved it

#### Scenario: A change that resolves nothing
- **WHEN** config has a conflict on `tester` and a person sets a value of `reviewer` only
- **THEN** it is refused with `config.conflict`, naming the conflict left

### Requirement: Settling a fork is recorded with the next write
Reading a forked config stream SHALL record nothing. The next change recorded to it SHALL be preceded, in the same
batch, by a settling event whose parents are every head and whose state is the merged config.

#### Scenario: A read after a merge
- **WHEN** two branches' config changes are merged and a person runs `troupe config get`
- **THEN** no event is recorded

#### Scenario: The first write after a merge
- **WHEN** a person then runs `troupe config set`
- **THEN** one batch records a settling event naming both heads, then the change
- **AND** the stream has one head

### Requirement: An actor is defined by its runner, options, effect check and character
An actor SHALL have a `runner` (required), `options` (an object, default empty), `expect` (required: theatre-relative
paths the run must create or change, where an empty list means no effect check), an optional `character` (text) and
an optional `workspace`: `worktree` (the default when it's absent) or `theatre`. Its name SHALL match the client
protocol's actor-name pattern.

#### Scenario: An actor with no effect check written
- **WHEN** a person sets only `actors.tester.runner`
- **THEN** it is refused, saying `expect` is required and that `[]` means no effect check

#### Scenario: An effect check path outside the theatre
- **WHEN** a person sets `actors.tester.expect` to `["../elsewhere.txt"]`
- **THEN** it is refused, naming the path

#### Scenario: An actor name that doesn't fit
- **WHEN** a person sets `actors.Tester.runner`
- **THEN** it is refused, naming the name and the pattern

#### Scenario: Running in place
- **WHEN** a person runs `troupe config set actors.tester.workspace=theatre`
- **THEN** `tester`'s runs work in the theatre

#### Scenario: A workspace that doesn't exist
- **WHEN** a person sets `actors.tester.workspace` to `sandbox`
- **THEN** it is refused, naming the path, `sandbox`, and the accepted values `worktree` and `theatre`

### Requirement: Config commands
`troupe config set <path>=<value>…` SHALL set values, with `<path>=@<file>` reading a value from a file;
`troupe config unset <path>…` SHALL remove values or groups; and `troupe config get [<path>]` SHALL show the merged
config, or the value or group at a path. A change SHALL accept `--reason`, recorded in its lineage.

#### Scenario: A character from a file
- **WHEN** a person runs `troupe config set actors.tester.character=@tester-character.md`
- **THEN** the character is that file's text exactly

#### Scenario: A reason
- **WHEN** a person runs `troupe config set actors.tester.runner=scripted --reason "offline tests"`
- **THEN** the change's lineage records the reason

### Requirement: Command-line values are typed by the schema
The CLI SHALL type a value by the schema at its path: a string as given, an integer, number or boolean parsed
strictly, and an array as JSON. Where the schema doesn't give one type, the value SHALL be refused unless it is
given as JSON with `--json`, naming the path.

#### Scenario: A number for a string field
- **WHEN** a person sets a string field to `3`
- **THEN** the value is the string `"3"`

#### Scenario: A boolean that isn't one
- **WHEN** a person sets a boolean field to `yes`
- **THEN** it is refused, naming the path and saying to write `true` or `false`

### Requirement: Config's types are generated from its schemas
troupe's types for config SHALL be generated from the config schemas in `protocol/`, and the quality check SHALL fail
when they aren't what the schemas generate. Each type SHALL accept exactly what its schema accepts.

#### Scenario: A schema changed without its types
- **WHEN** a field is added to `actor.schema.json` and the types aren't regenerated
- **THEN** `scripts/check.py` fails, naming the generated file and the command that regenerates it

#### Scenario: Types and schemas agree
- **WHEN** generated inputs and near misses (unknown keys, wrong types, values outside a pattern) are checked by both
  a type and its schema
- **THEN** both accept or both refuse each one
