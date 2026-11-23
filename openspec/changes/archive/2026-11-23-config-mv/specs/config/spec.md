## MODIFIED Requirements

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

#### Scenario: A removal another value's conflict leaves out
- **WHEN** one branch removes `tester` and another sets its character, a settle joins them, and two branches from the
  settle then conflict on `tester`'s `expect`, one of them by removing `tester`
- **THEN** every order the events arrive in works out the same config and the same conflicts

### Requirement: A change entry holds the path, the old value's hash and the new value
Each entry in a `Config.Changed` SHALL hold the value's path as an array of keys, `before` as `sha256:` and the
SHA-256 of the old value's canonical JSON, and `after` as the new value. `before` SHALL be absent when the value
didn't exist, and `after` absent when it was removed. Neither SHALL be null. A rename entry also holds `renamedFrom`
and is described by "A rename is one entry naming the old name" (spec: config-renames).

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

### Requirement: Config commands
`troupe config set <path>=<value>…` SHALL set values, with `<path>=@<file>` reading a value from a file;
`troupe config unset <path>…` SHALL remove values or groups; `troupe config mv <kind>.<old> <kind>.<new>` SHALL rename
an actor or a runtime; and `troupe config get [<path>]` SHALL show the merged config, or the value or group at a path,
and with `--resolved`, a runtime's resolved values (spec: runtimes). A change SHALL accept `--reason`, recorded in its
lineage.

#### Scenario: A character from a file
- **WHEN** a person runs `troupe config set actors.tester.character=@tester-character.md`
- **THEN** the character is that file's text exactly

#### Scenario: A reason
- **WHEN** a person runs `troupe config set actors.tester.runner=scripted --reason "offline tests"`
- **THEN** the change's lineage records the reason

#### Scenario: Resolved runtimes
- **WHEN** a person runs `troupe config get --resolved`
- **THEN** it shows every runtime, built-in or in config, with each value's source

#### Scenario: A rename with a reason
- **WHEN** a person runs `troupe config mv actors.tester actors.qa --reason "clearer name"`
- **THEN** one change renames `tester` to `qa`, and its lineage records the reason
