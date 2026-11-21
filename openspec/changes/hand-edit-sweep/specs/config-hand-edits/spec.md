## Purpose

Capability: `cap:config`, `cap:projections`, `cap:lineage`

Reads a person's edits to the config files under `.troupe/` back into config, recording each meaningful one as a
change with lineage, and never mistaking a half-saved or invalid file for a removal.

## ADDED Requirements

### Requirement: Every command that uses config sweeps first
Before `troupe perform`, `troupe config set`, `troupe config unset`, `troupe config get` and `troupe sync` use config,
troupe SHALL sweep the config files: read each one's values, and record each meaningful hand edit before the command
goes on. The command SHALL then use config as the sweep left it.

#### Scenario: Perform uses a hand edit
- **WHEN** a person changes `runner` in `.troupe/actors/tester.yaml` from `scripted` to `claude-code`, and runs
  `troupe perform tester --rehearse`
- **THEN** the rehearsal shows the runner `claude-code`

#### Scenario: Config get shows what the file says
- **WHEN** a person changes `runner` in `.troupe/actors/tester.yaml` to `claude-code`, and runs `troupe config get
  actors.tester.runner`
- **THEN** it prints `claude-code`
- **AND** one change is recorded, setting `actors.tester.runner`

#### Scenario: The command reports the edit
- **WHEN** a person edits `.troupe/actors/tester.yaml` and runs `troupe config set actors.reviewer.runner=scripted`
- **THEN** a `config.hand-edit-recorded` notice names the file and the change id of what was recorded

#### Scenario: A command that doesn't use config doesn't sweep
- **WHEN** a person edits `.troupe/actors/tester.yaml` and runs `troupe status`
- **THEN** nothing is recorded

### Requirement: Only a change in values is a change
The sweep SHALL compare a file's values with what config holds for that file, and SHALL record only values that
differ. Comments, key order, quoting, indentation and blank lines SHALL never be a change, and a file whose values are
what config holds SHALL be left as it is.

#### Scenario: A comment and a new order
- **WHEN** a person adds a comment to `.troupe/actors/tester.yaml`, moves `expect` above `runner`, and runs `troupe
  sync`
- **THEN** nothing is recorded, and the file is byte for byte as the person left it

#### Scenario: Several edits between two commands
- **WHEN** a person changes an actor's `model` from `a` to `b` and then to `c` between two commands
- **THEN** the sweep records one change, from `a` to `c`

#### Scenario: An edit and its undo between two commands
- **WHEN** a person changes `model` from `a` to `b` and back to `a` between two commands
- **THEN** the sweep records nothing

#### Scenario: A character edited
- **WHEN** a person edits `.troupe/actors/tester.md` and runs `troupe sync`
- **THEN** one change sets `actors.tester.character` to the file's whole text, byte for byte

### Requirement: Each edited file is recorded as its own change by an unknown author
The sweep SHALL record each file whose values changed as one `Config.Changed`, whose lineage has the actor kind
`unknown`, `via` `file`, no reason, and `vcs.source` naming the file with its content hash before and after. Its
`files` SHALL hold the file's hash. One sweep's changes SHALL share one change id, apart from the command's own.

#### Scenario: The lineage of a hand edit
- **WHEN** `TROUPE_ACTOR` names a person, they edit `.troupe/actors/tester.yaml` by hand, and run `troupe sync`
- **THEN** the change's actor has kind `unknown`, not the person, and its `via` is `file`
- **AND** its `vcs.source` names `.troupe/actors/tester.yaml`, with the hash of the bytes troupe last saw as `before`
  and of the edited bytes as `after`

#### Scenario: Two files edited
- **WHEN** a person edits `.troupe/actors/tester.yaml` and `.troupe/actors/reviewer.md`, and runs `troupe sync`
- **THEN** two changes are recorded, one naming each file, with the same change id

#### Scenario: A hand edit before a config set
- **WHEN** a person edits `.troupe/actors/tester.yaml` by hand, and runs `troupe config set
  actors.reviewer.runner=scripted`
- **THEN** the hand edit's change is recorded first, with actor `unknown`, then the person's change, with its own
  change id

### Requirement: Adding or deleting a file adds or removes what it held
A config file that config doesn't hold SHALL be read as adding what it holds. A config file deleted by hand SHALL be
read as removing what it held: an actor's `.md` file its character, and its `.yaml` and `.md` files together the
actor.

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
- **AND** nothing is recorded

#### Scenario: A runtime file deleted
- **WHEN** config sets `runtimes.openai.model`, and a person deletes `.troupe/runtimes/openai.yaml` and runs `troupe
  sync`
- **THEN** one change removes the group `runtimes.openai`

### Requirement: A restored file is recorded as an edit
A file put back to an earlier version, by `git restore`, `git checkout` of the file, or any other means, SHALL be
read like any other hand edit: when its values differ from config, the difference SHALL be recorded, and the file SHALL
stay as restored, even when troupe wrote that version.

#### Scenario: An edit undone with git restore
- **WHEN** a person changes `runner` in `.troupe/actors/tester.yaml` from `scripted` to `claude-code`, runs `troupe
  sync`, then runs `git restore .troupe/actors/tester.yaml` and `troupe sync`
- **THEN** a second change sets `actors.tester.runner` back to `scripted`, and the file is as git restored it

#### Scenario: A file restored from an earlier commit
- **WHEN** config has changed `tester`'s runner since an earlier commit, and a person runs `git checkout <commit> --
  .troupe/actors/tester.yaml` and `troupe sync`
- **THEN** a change sets the runner to the earlier commit's, and the file is as git checked it out

### Requirement: A file with no values is never a removal
A config file that is present but holds no values, because it is empty or holds only its schema lines, SHALL be
refused with `config.file-invalid`, saying that deleting the file removes what it held. It SHALL NOT be read as
removing anything, and nothing from any file SHALL be recorded.

#### Scenario: An editor's empty file mid-save
- **WHEN** `.troupe/actors/tester.yaml` is empty and a person runs `troupe perform tester`
- **THEN** it is refused with `config.file-invalid`, naming the file and saying it's empty
- **AND** nothing is recorded, `tester` is unchanged in config, and the run doesn't start

#### Scenario: Only the schema lines left
- **WHEN** `.troupe/runtimes/openai.yaml` holds only its language-server comment and its `$schema` key, and a person
  runs `troupe sync`
- **THEN** it is refused with `config.file-invalid`, saying to delete the file to remove the runtime

#### Scenario: An empty character file
- **WHEN** `.troupe/actors/tester.md` is empty and a person runs `troupe sync`
- **THEN** it is refused with `config.file-invalid`, saying that deleting the file removes the character

### Requirement: An invalid file is refused, never skipped
A config file that doesn't parse, or whose values fail its kind's schema or, for an actor, its runner's options
schema, SHALL be refused with `config.file-invalid`, naming the file, the rule and the fix, without repeating the
value. Nothing from any file SHALL be recorded, and the command SHALL NOT go on.

#### Scenario: YAML that doesn't parse
- **WHEN** `.troupe/actors/tester.yaml` has a tab where YAML needs spaces, and a person runs `troupe sync`
- **THEN** it is refused with `config.file-invalid`, naming the file, the line and the column
- **AND** nothing is recorded

#### Scenario: A misspelt field
- **WHEN** a person renames `runner` to `runnr` in `.troupe/actors/tester.yaml`, and runs `troupe sync`
- **THEN** it is refused with `config.file-invalid`, naming the file and saying the actor has no field `runnr`

#### Scenario: Options the runner doesn't define
- **WHEN** a person adds `speed: 3` under `options` in a scripted actor's file, and runs `troupe sync`
- **THEN** it is refused with `config.file-invalid`, naming the file, `actors.tester.options.speed` and the scripted
  runner's options schema

#### Scenario: One invalid file stops every file's edit
- **WHEN** a person edits `.troupe/actors/tester.yaml` validly and leaves `.troupe/actors/reviewer.yaml` invalid, and
  runs `troupe sync`
- **THEN** it is refused with `config.file-invalid`, naming `reviewer.yaml`
- **AND** nothing is recorded for either file

#### Scenario: Another kind's schema
- **WHEN** `$schema` in `.troupe/actors/tester.yaml` names the runtime schema, and a person runs `troupe sync`
- **THEN** it is refused with `config.file-invalid`, saying the file must name the actor schema

### Requirement: A file that changes while troupe reads it is read again
The sweep SHALL check that a file is the same before and after it reads it. A file that changed SHALL be read again, a
bounded number of times set by a named setting's default, and then refused with `config.file-changing`, naming the
file and saying to finish saving it.

#### Scenario: A save during the read
- **WHEN** a file changes once while the sweep reads it, then stays still
- **THEN** the sweep reads it again and records its final values

#### Scenario: A file that keeps changing
- **WHEN** a file changes every time the sweep reads it
- **THEN** it is refused with `config.file-changing`, naming the file, and nothing is recorded

### Requirement: troupe's own writes are never read as edits
A file troupe wrote, or wrote back surgically, SHALL read back as in line, so the next sweep records nothing for it. A
staged write that a recorded change vouches for SHALL be finished before the sweep reads its target.

#### Scenario: A config set, then another command
- **WHEN** a person runs `troupe config set actors.tester.model=b` on a file they had formatted by hand, then
  `troupe sync`
- **THEN** the sync records nothing and writes nothing

#### Scenario: A write a crash cut short
- **WHEN** troupe recorded a change and stopped before moving `.tester.yaml.troupe~` into place, and the next command
  runs
- **THEN** the staged file is moved into place, and the sweep records nothing for `tester.yaml`

### Requirement: A file git merged from troupe's versions isn't read as an edit
A config file git merged from versions troupe wrote, as config-files defines it, SHALL NOT be read by the sweep while
it is still what git made, and follows the rules for merged files. Once a person has edited it, with no conflict
markers left, it SHALL be read as their edit.

#### Scenario: A clean merge left as git made it
- **WHEN** git merged `.troupe/actors/tester.yaml` cleanly from two versions troupe wrote, and a person runs `troupe
  sync`
- **THEN** the sweep records nothing for it, and the file is rewritten from the merged config if it differs

#### Scenario: A conflict resolved by hand
- **WHEN** git left `.troupe/actors/tester.yaml` conflicted from two versions troupe wrote, the person removes every
  conflict marker, keeping `runner: claude-code`, and runs `troupe sync`
- **THEN** the file is read as their edit, and config's runner is `claude-code`

#### Scenario: Markers still in the file
- **WHEN** the person removed some of the markers but not all, and runs `troupe sync`
- **THEN** the sweep doesn't read it, and the file is rewritten from the merged config, keeping a copy, as before

### Requirement: Hand edits resolve config's conflicts
While config has conflicts, the values a hand-edited file holds at each conflicting path SHALL count as setting them,
even when one equals a side's value, and a conflicting value whose file was deleted SHALL count as unsetting it. The
sweep's changes and the command's own SHALL be recorded in one batch only if together they set or unset every
conflicting value.

#### Scenario: A hand edit resolves a conflict
- **WHEN** two merged branches set `actors.tester.runner` to `scripted` and `claude-code`, and a person sets
  `runner: claude-code` in `.troupe/actors/tester.yaml` and runs `troupe sync`
- **THEN** a change by the `unknown` actor sets the runner to `claude-code`, after a settle naming both heads
- **AND** config has no conflict, and the sync goes on to write the files

#### Scenario: A value that matches neither side
- **WHEN** the branches set the runner to `scripted` and `claude-code`, and the person sets `runner: ollama` in the
  file
- **THEN** the conflict is resolved, and config's runner is `ollama`

#### Scenario: A partial resolution
- **WHEN** the branches conflict on both `actors.tester.runner` and `actors.reviewer.model`, and the person edits
  only `.troupe/actors/tester.yaml`'s runner and runs `troupe sync`
- **THEN** it is refused with `config.conflict`, naming `actors.reviewer.model` as left
- **AND** nothing is recorded, and `.troupe/actors/tester.yaml` keeps the person's edit

#### Scenario: A partial resolution finished by the command
- **WHEN** the person edits `tester`'s runner in its file, and runs `troupe config set actors.reviewer.model=m`
- **THEN** one batch records the settle, the hand edit's change and the person's change, and config has no conflict

#### Scenario: Config get with a partial resolution
- **WHEN** the person edits only `tester`'s runner, and runs `troupe config get`
- **THEN** nothing is recorded, it shows both conflicts, and a notice says the edit to `.troupe/actors/tester.yaml`
  isn't recorded until every conflicting value is set

#### Scenario: Taking a side with git
- **WHEN** the branches conflict on `tester`'s runner, git left `.troupe/actors/tester.yaml` conflicted, and the person
  runs `git checkout --theirs .troupe/actors/tester.yaml` and `troupe sync`
- **THEN** the file is read as their edit, and config's runner is the other branch's

#### Scenario: A merge git made resolves nothing
- **WHEN** the branches conflict on `tester`'s runner, `.troupe/actors/tester.yaml` is still the merge git made from
  versions troupe wrote, and a person runs `troupe perform tester`
- **THEN** it is refused with `config.conflict`, and nothing is recorded

### Requirement: A sweep can be rehearsed
`troupe sync --rehearse`, and every command's `--rehearse`, SHALL show the hand edits the sweep would record, file by
file, with every check the real sweep runs, and SHALL record nothing and write nothing.

#### Scenario: Rehearsing a sync after a hand edit
- **WHEN** a person edits `.troupe/actors/tester.yaml` and runs `troupe sync --rehearse`
- **THEN** it shows the change it would record for the file, and exits with the "would change" code
- **AND** nothing is recorded or written

#### Scenario: Rehearsing a sweep that would be refused
- **WHEN** `.troupe/actors/tester.yaml` is empty and a person runs `troupe sync --rehearse`
- **THEN** it exits with the code of `config.file-invalid`, naming the file
