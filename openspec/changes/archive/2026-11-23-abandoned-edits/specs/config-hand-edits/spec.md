## ADDED Requirements

### Requirement: An edit undone by hand is reported as abandoned
When a sweep records a hand edit that puts a file's values back to what they were before an earlier run of recorded
changes to that file, whoever made those changes, the command SHALL report a `config.edit-abandoned` notice naming
the file, the changes since, and whether they can be dropped. Values are compared, never formatting.

#### Scenario: An edit undone with git restore
- **WHEN** a person changes `runner` in `.troupe/actors/tester.yaml` from `scripted` to `claude-code`, runs `troupe
  sync`, then runs `git restore .troupe/actors/tester.yaml` and `troupe sync`
- **THEN** the second sync records the edit back, and reports `config.edit-abandoned` naming the file and both
  changes, saying they can be dropped
- **AND** the notice names `troupe config drop` and `troupe config keep` with the second sync's change id

#### Scenario: Back with a comment the original didn't have
- **WHEN** the person puts `runner: scripted` back by hand, with a comment the file didn't have before, and runs
  `troupe sync`
- **THEN** `config.edit-abandoned` is reported, since the values are back

#### Scenario: Several steps undone
- **WHEN** `runner` goes from `scripted` to `claude-code` and then to `ollama`, with a `troupe sync` after each, and
  the file is then restored and synced
- **THEN** `config.edit-abandoned` names all three changes

#### Scenario: A partial undo
- **WHEN** a person changes `runner` and `model`, syncs, then puts back only `runner` and syncs
- **THEN** no `config.edit-abandoned` is reported

#### Scenario: A config set undone by git restore
- **WHEN** a person runs `troupe config set actors.tester.model=b`, then `git restore .troupe/actors/tester.yaml` and
  `troupe sync`
- **THEN** `config.edit-abandoned` names the config set's change and the edit back

#### Scenario: Only the latest round trip
- **WHEN** `runner` goes `scripted`, `claude-code`, `scripted`, `claude-code`, `scripted`, with a sync after each
- **THEN** the last sync's notice names only the last two changes

#### Scenario: A stash is a restore like any other
- **WHEN** a person edits `.troupe/actors/tester.yaml`, syncs, runs `git stash` and `troupe sync`
- **THEN** `config.edit-abandoned` is reported, as for any restore

#### Scenario: A deleted actor restored
- **WHEN** a person deletes `.troupe/actors/tester.yaml` and `.troupe/actors/tester.md`, syncs, restores both with
  `git restore` and syncs
- **THEN** one `config.edit-abandoned` names both files, the removal and the two edits back

### Requirement: An abandoned edit that can't be dropped says why
An abandoned edit SHALL be droppable only when its changes are the end of the config stream, nothing refers to them,
they change nothing outside the files that went back, and each is alone in an uncommitted event file of this branch.
Otherwise its notice SHALL say it is kept and name the first reason that holds, and what blocks it.

#### Scenario: A run used the edit
- **WHEN** a person edits `tester.yaml`, runs `troupe perform tester`, restores the file and runs `troupe sync`
- **THEN** `config.edit-abandoned` says the changes are kept because the run used them, naming the run

#### Scenario: Restored, then performed
- **WHEN** a person edits `tester.yaml`, syncs, restores the file and runs `troupe perform tester`
- **THEN** before the run starts, `config.edit-abandoned` says the changes are kept because the run uses them

#### Scenario: Committed
- **WHEN** a person edits `tester.yaml`, syncs, commits, restores the file and syncs
- **THEN** `config.edit-abandoned` says the changes are kept because they're committed

#### Scenario: A change builds on it
- **WHEN** a person edits `tester.yaml`, syncs, restores the file and runs `troupe config set
  actors.reviewer.model=m`
- **THEN** `config.edit-abandoned` says the changes are kept because the config set's change builds on them

#### Scenario: Another file changed in between
- **WHEN** a person edits `tester.yaml` and syncs, edits `reviewer.yaml` and syncs, then restores `tester.yaml` and
  syncs
- **THEN** `config.edit-abandoned` says the changes are kept because the edit to `reviewer.yaml` is among them

### Requirement: A person drops or keeps an abandoned edit
`troupe config drop <change>` SHALL remove the abandoned edit's events, recording nothing and writing no config file,
and only while it can be dropped; otherwise it SHALL be refused, naming why, and remove nothing. `troupe config keep
<change>` SHALL keep them and stop troupe asking about them. Nothing SHALL be dropped without a drop.

#### Scenario: Dropping a round trip
- **WHEN** a person edits `tester.yaml`, syncs, restores it, syncs, and runs `troupe config drop <change>` with the
  change id the notice named
- **THEN** the event files of both syncs are removed, and config's history has neither change
- **AND** config and `.troupe/actors/tester.yaml` are as they were before the edit, and the next `troupe sync`
  records nothing

#### Scenario: Rehearsing a drop
- **WHEN** the person runs `troupe config drop <change> --rehearse` instead
- **THEN** it names the changes and event files it would remove, exits with the "would change" code, and removes
  nothing

#### Scenario: A drop no longer safe
- **WHEN** a notice offered a drop, the person then runs `troupe perform tester`, and then `troupe config drop
  <change>`
- **THEN** it is refused with `config.round-trip-kept`, naming the run, and nothing is removed

#### Scenario: A drop that lands before a run's start
- **WHEN** a person runs `troupe perform tester` while a droppable abandoned edit is at the head of config, and a
  `troupe config drop` of it lands after the perform reads config and before it records the run's start
- **THEN** the perform is refused with `events.required-missing` before its runner starts, and no run is recorded

#### Scenario: A change that closes no round trip
- **WHEN** a person runs `troupe config drop` with a change id that closed no abandoned edit
- **THEN** it is refused with `config.no-round-trip`, naming the change

#### Scenario: Keeping a round trip
- **WHEN** a person runs `troupe config keep <change>` after the notice, and then `troupe sync`
- **THEN** the changes stay in history, and the sync doesn't report `config.edit-abandoned` for them

#### Scenario: A keep lives in this clone only
- **WHEN** a person keeps a round trip
- **THEN** the record of it is under `.troupe/local/`, and `git status` shows no new file for it

### Requirement: Sync asks again while a drop is possible
`troupe sync` SHALL report `config.edit-abandoned` again for an abandoned edit that can still be dropped and that the
person hasn't kept. Other commands SHALL report it only when their own sweep records the edit back. An unanswered
abandoned edit SHALL be kept.

#### Scenario: No answer, then another sync
- **WHEN** a sync reported a droppable abandoned edit, the person doesn't answer, and runs `troupe sync` again
- **THEN** the notice is reported again, and nothing is dropped

#### Scenario: Other commands stay quiet
- **WHEN** a sync reported a droppable abandoned edit, and the person runs `troupe config get`
- **THEN** no `config.edit-abandoned` is reported

#### Scenario: Once it can't be dropped, no more asking
- **WHEN** a sync reported a droppable abandoned edit, and the person commits the event files and runs `troupe sync`
- **THEN** no `config.edit-abandoned` is reported, and the changes stay in history

#### Scenario: An unreadable keep record
- **WHEN** troupe's record of kept round trips can't be read, and a person runs `troupe sync`
- **THEN** a `config.kept-unreadable` notice names it, and a droppable abandoned edit is reported again
