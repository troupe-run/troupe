## ADDED Requirements

### Requirement: Sync makes the files say what config says
`troupe sync` SHALL sweep the config files (spec: config-hand-edits), then make every config file say what config
says, adding, writing back and removing files, and SHALL report each hand edit it recorded and each file it changed
and why. Every command that uses config SHALL sync first, and SHALL stop if the sync is refused.

#### Scenario: A new actor's files
- **WHEN** a person runs `troupe config set actors.qa.runner=scripted 'actors.qa.expect=[]'`
- **THEN** `.troupe/actors/qa.yaml` is written, with a notice naming it

#### Scenario: Perform syncs first
- **WHEN** a person edits `.troupe/actors/tester.yaml` and runs `troupe perform tester`
- **THEN** the hand edit is recorded before the run starts

#### Scenario: Nothing to do
- **WHEN** every config file already says what config says
- **THEN** `troupe sync` records nothing, changes nothing and says so

### Requirement: A file troupe can't read is never replaced
Before replacing or removing a file, troupe SHALL check that the sweep read it. A file the sweep refused, or one with
git's conflict markers that git didn't merge only from versions troupe wrote, SHALL be refused, naming the file and
the fix, and nothing SHALL be written.

#### Scenario: An invalid hand edit
- **WHEN** a person leaves `.troupe/actors/tester.yaml` invalid and runs `troupe config set
  actors.tester.model=m`
- **THEN** it is refused with `config.file-invalid`, naming the file and saying to fix it or run `troupe sync
  --force`
- **AND** nothing is recorded or written

#### Scenario: A file git left conflicted
- **WHEN** git merges two branches that changed `.troupe/actors/tester.md`, leaves its conflict markers in the file,
  and a person runs `troupe config set actors.tester.character=Both.`
- **THEN** the command is accepted, and `.troupe/actors/tester.md` holds `Both.`
- **AND** a `config.merge-rewritten` notice names the file and the hash its conflicted bytes are kept under

#### Scenario: A conflicted file with a side troupe didn't write
- **WHEN** one branch's `.troupe/actors/tester.yaml` was edited by hand and committed, git merges it with another
  branch's change to the file and leaves it conflicted, and a person runs `troupe sync`
- **THEN** it is refused with `config.file-not-troupes`, saying the file has git's conflict markers in it, naming the
  side troupe didn't write, and saying to take the side troupe wrote with `git checkout --ours` or `--theirs`, to
  resolve the markers by hand, or to run `troupe sync --force`
- **AND** nothing is written

#### Scenario: A clean merge of two branches' files
- **WHEN** git merges two branches' changes to `.troupe/actors/tester.yaml` without a conflict, giving exactly what
  the merged config would write
- **THEN** syncing records nothing and leaves the file as it is

### Requirement: Write-back changes only what it must
When troupe writes a config file that exists, it SHALL change only the values that changed: replace a changed value
where it stands, remove a removed key and its value, and add a new key where the schema's order puts it among the keys
already there. Every other line SHALL stay byte for byte. A file troupe makes new SHALL be written whole.

#### Scenario: A changed value in a formatted file
- **WHEN** `.troupe/actors/tester.yaml` has the person's comments, blank lines and key order, and a person runs
  `troupe config set actors.tester.runner=claude-code`
- **THEN** only the line holding `runner`'s value changes, keeping a comment at its end
- **AND** every other line is byte for byte as before

#### Scenario: A new key among the person's keys
- **WHEN** the person's file holds `expect` above `runner` with a comment between them, and `troupe config set
  actors.tester.model=m` runs
- **THEN** `model: m` is added after the last key the schema puts before `model`, and the person's lines are
  unchanged

#### Scenario: A removed key
- **WHEN** `troupe config unset actors.tester.model` runs on the person's file
- **THEN** the lines holding `model` and its value are removed, and every other line is unchanged

#### Scenario: A list replaced whole
- **WHEN** `troupe config set 'actors.tester.expect=["a","b"]'` runs on a file whose `expect` the person wrote as a
  block list with a comment on each item
- **THEN** the whole of `expect`'s value is replaced, and the lines around it are unchanged

#### Scenario: A character replaced whole
- **WHEN** `troupe config set actors.tester.character=New.` runs
- **THEN** `.troupe/actors/tester.md` holds exactly `New.`

#### Scenario: The written-back file reads as config says
- **WHEN** any change is written back into any file a person formatted
- **THEN** the file's values are what config holds, and the next sweep records nothing

### Requirement: A file is replaced only while it's what the sweep read
Holding the config files' lock, troupe SHALL check before replacing or removing a file that its bytes are still those
the sweep read. A file that changed since SHALL be refused with `config.file-changing`, naming the file, and nothing
SHALL be written.

#### Scenario: An edit between the sweep and the write
- **WHEN** a person saves `.troupe/actors/tester.yaml` after the sweep read it and before troupe writes it back
- **THEN** the command is refused with `config.file-changing`, and the person's file is unchanged

### Requirement: Only sync or a resolving change rewrites a file git merged
A file merged from troupe's versions SHALL be rewritten only by `troupe sync`, or by a `troupe config set` whose
change writes that file or resolves config's conflicts. Any other command that uses config SHALL refuse it with
`config.file-not-troupes`, saying that `troupe sync` rewrites it from the merged config, keeping a copy.

#### Scenario: Another command refuses it and names sync
- **WHEN** git left `.troupe/actors/tester.yaml` conflicted, config has no conflict, and a person runs `troupe
  perform tester`
- **THEN** it is refused with `config.file-not-troupes`, saying the file is a merge of versions troupe wrote and that
  `troupe sync` rewrites it from the merged config, keeping a copy
- **AND** the file is unchanged, and the run doesn't start

#### Scenario: The config set that resolves a conflict rewrites every merged file
- **WHEN** two branches set `actors.tester.character` differently and also change `tester`'s options and effect
  check, git leaves both `.troupe/actors/tester.md` and `.troupe/actors/tester.yaml` conflicted, and a person runs
  `troupe config set actors.tester.character=Both.`
- **THEN** the command is accepted, `.troupe/actors/tester.md` holds `Both.`, and `.troupe/actors/tester.yaml` is
  what the merged config writes
- **AND** each file's conflicted bytes are kept

#### Scenario: A config set that doesn't write the file
- **WHEN** git left `.troupe/actors/tester.yaml` conflicted, config has no conflict, and a person runs `troupe config
  set actors.reviewer.runner=scripted`
- **THEN** it is refused with `config.file-not-troupes`, naming `troupe sync`
- **AND** nothing is recorded or written

### Requirement: A write-back that wouldn't read as config says is refused
Before staging a written-back file, troupe SHALL read the bytes it would write and check they give exactly what config
holds for the file. When they don't, the command SHALL be refused with `config.write-back-failed`, naming the file and
saying that `troupe sync --force` writes it whole, keeping a copy, and nothing SHALL be recorded or written.

#### Scenario: A splice that would misread
- **WHEN** writing a change back into a person's file would give bytes that read as other values
- **THEN** the command is refused with `config.write-back-failed`, naming the file
- **AND** nothing is recorded, and the file is unchanged

## MODIFIED Requirements

### Requirement: Each actor is projected to its own files
Each actor in config SHALL be written to `.troupe/actors/<name>.yaml`, holding every field of the actor schema that
config sets, other than the character, and its character, when it has one, to `.troupe/actors/<name>.md`, whose whole
content is the character's text. A `.yaml` file troupe makes new SHALL hold its fields in the schema's order. An actor
with no character SHALL have no `.md` file.

#### Scenario: An actor with a character
- **WHEN** config has the actor `tester` with a runner, an effect check and a character
- **THEN** `.troupe/actors/tester.yaml` holds the runner and the effect check
- **AND** `.troupe/actors/tester.md` holds the character's text, byte for byte

#### Scenario: An actor's effects, workspace, runtime and model
- **WHEN** a person runs `troupe config set actors.tester.runner=scripted 'actors.tester.expect=[]'
  'actors.tester.effects.write=["out/**"]' actors.tester.workspace=theatre actors.tester.runtime=ollama
  actors.tester.model=llama3.2`
- **THEN** `.troupe/actors/tester.yaml` holds `runner`, `expect`, `effects`, `workspace`, `runtime` and `model`, in
  the actor schema's order

#### Scenario: Every field config can set
- **WHEN** config sets every field the actor schema defines
- **THEN** the actor's file holds each of them, so a field added to the schema later can't be left out

#### Scenario: The file validates against its schema
- **WHEN** a written actor file is validated against the actor schema troupe carries
- **THEN** it is valid

#### Scenario: A removed actor
- **WHEN** `tester` is removed from config
- **THEN** its `.yaml` and `.md` files are removed

### Requirement: Each config file names its schema twice
Each YAML config file troupe makes new SHALL begin with a `# yaml-language-server: $schema=<url>` comment and a
`$schema: <url>` key, both naming its kind's schema at troupe.run by the major version of the protocol troupe carries.

#### Scenario: An actor file names its schema
- **WHEN** an actor file is written by a troupe that carries protocol 0.2.0
- **THEN** its first line is the language-server comment and its first key is `$schema`, both naming
  `https://troupe.run/protocol/0/config/actor.schema.json`

#### Scenario: A protocol past 1.0
- **WHEN** an actor file is written by a troupe that carries protocol 1.3.0
- **THEN** both name `https://troupe.run/protocol/1/config/actor.schema.json`

#### Scenario: The file validates against its schema
- **WHEN** a written actor file is validated against the actor schema troupe carries
- **THEN** it is valid

### Requirement: A file git merged from troupe's versions is rewritten from the merged config
A config file SHALL count as merged from troupe's versions when git left it unmerged, or merged it cleanly in the merge
in progress or in HEAD's merge commit, and every side it came from is a version troupe recorded. When rewriting one,
troupe SHALL write or remove it as the merged config says, keep its bytes in the artifact store first, and report
`config.merge-rewritten` naming the file, the kept hash, and whether troupe marked it resolved in git's index.

#### Scenario: Config merged cleanly but the file conflicted
- **WHEN** one branch sets `actors.tester.runner` and another sets one of `tester`'s options, git leaves
  `.troupe/actors/tester.yaml` conflicted, and a person runs `troupe sync`
- **THEN** the file is what the merged config writes, holding both branches' changes
- **AND** with `mark_merges_resolved` unset, the notice names the file and its kept hash, and says to `git add` it and
  commit the merge
- **AND** git still shows the file as unmerged

#### Scenario: A config conflict and a conflicted file
- **WHEN** two branches set `actors.tester.character` to different text, git leaves `.troupe/actors/tester.md`
  conflicted, and a person runs `troupe config set actors.tester.character=Both.`
- **THEN** the config conflict is resolved and the file holds `Both.`
- **AND** the conflicted bytes are kept, and the notice names their hash

#### Scenario: A resolution started by hand is kept
- **WHEN** git left `.troupe/actors/tester.md` conflicted, the person deleted some of the markers by hand, and runs
  `troupe sync`
- **THEN** the file is rewritten from the merged config
- **AND** the artifact store holds the bytes the person left, under the hash the notice names

#### Scenario: Removed on one side, changed on the other
- **WHEN** one branch removes `tester`'s character and another changes it, git leaves `.troupe/actors/tester.md`
  unmerged with the changed side in place, and a person resolves config with `troupe config set`
- **THEN** the file is written or removed as the resolved config says
- **AND** no copy is kept, since the file in place is a version troupe wrote

#### Scenario: git merged the lines cleanly but config conflicts
- **WHEN** two branches change different paragraphs of `tester`'s character, git merges and commits
  `.troupe/actors/tester.md` without a conflict, and a person runs `troupe config set actors.tester.character=Both.`
- **THEN** the command is accepted, and the file holds `Both.`
- **AND** a `config.merge-rewritten` notice names the file and the hash its merged bytes are kept under

#### Scenario: A clean merge edited after git made it
- **WHEN** git merged `.troupe/actors/tester.md` cleanly, the person then edited the file, and runs `troupe sync`
- **THEN** the sweep reads it as the person's edit, as any hand edit is

#### Scenario: A merge older than HEAD
- **WHEN** git merged `.troupe/actors/tester.md` cleanly in a merge commit that has commits after it, and the file
  isn't a version troupe wrote
- **THEN** the sweep reads it as a hand edit

#### Scenario: A rehearsal
- **WHEN** git left `.troupe/actors/tester.yaml` conflicted, and a person runs `troupe sync --rehearse`
- **THEN** the output names the file and says it would be rewritten because git merged it from versions troupe
  wrote
- **AND** nothing is written or kept

#### Scenario: Without git
- **WHEN** the theatre uses the plain filesystem adapter and `.troupe/actors/tester.yaml` holds conflict markers
- **THEN** syncing refuses it with `config.file-not-troupes`, as any conflicted file troupe can't read is

### Requirement: Force replaces a file and keeps a copy
`troupe sync --force` SHALL replace files the sweep or a check refused with what config says, first storing each
one's bytes in the artifact store and naming each file and the hash it was kept under. A file it replaces SHALL NOT
be read as an edit.

#### Scenario: Forcing past a hand edit
- **WHEN** a person runs `troupe sync --force` after leaving `.troupe/actors/tester.yaml` invalid
- **THEN** the file is what config says, and nothing is recorded for it
- **AND** the output names the file and the hash its edited bytes are kept under in the artifact store

### Requirement: A file is staged beside its target, then replaced atomically
troupe SHALL write each new file whole beside its target as `.<file>.troupe~` before recording the change, and move
it into place with an atomic replace after. A reader SHALL see the old file or the new one, never part of each.

#### Scenario: A staged file left by a crash after recording
- **WHEN** troupe recorded a change and stopped before moving `.tester.yaml.troupe~` into place, and the next command
  runs
- **THEN** the staged file is moved into place, because a recorded change names its hash

#### Scenario: A staged file left by a crash before recording
- **WHEN** a `.tester.yaml.troupe~` exists whose hash no change names
- **THEN** the next sync removes it, and config is unchanged

### Requirement: Config writes queue
Syncs and config changes SHALL hold a lock for the whole of sweeping, staging, recording and replacing, so two
commands writing config files never interleave. A wait SHALL be announced and bounded.

#### Scenario: Two terminals
- **WHEN** two `troupe config set` commands run at once in one theatre
- **THEN** one waits, says it is waiting, and runs after the other has replaced its files

### Requirement: Files in config directories are known kinds
Every file in a config directory SHALL match a kind in the registry of file kinds, be a staged write, or be a named
operating-system file. Any other file SHALL be refused when syncing, with `config.unknown-file`, naming it.
`events/`, `local/`, `.gitignore`, `.gitattributes` and `troupe.yaml` SHALL be reserved and never config.

#### Scenario: A stray file
- **WHEN** `.troupe/actors/notes.txt` exists and a person runs `troupe sync`
- **THEN** it is refused with `config.unknown-file`, naming the file

#### Scenario: Finder's metadata
- **WHEN** `.troupe/actors/.DS_Store` exists
- **THEN** syncing ignores it

### Requirement: A rewritten unmerged file is marked resolved when the setting is on
When the setting `mark_merges_resolved` is true and policy allows it, each config file a command writes or removes
whose path git's index holds unmerged, and whose every side is a version troupe wrote, SHALL be marked resolved in the
index, staging the bytes troupe wrote or the removal. Nothing else SHALL be staged. When the setting is false, its
default, the index SHALL be left alone.

#### Scenario: Marked resolved
- **WHEN** `TROUPE_SETTING_MARK_MERGES_RESOLVED` is `true`, git left `.troupe/actors/tester.yaml` conflicted from two
  versions troupe wrote, and a person runs `troupe sync`
- **THEN** the file is what the merged config writes, and git's index holds exactly those bytes for it, with no
  unmerged entry
- **AND** the `config.merge-rewritten` notice says troupe marked it resolved, and that the merge can be committed

#### Scenario: Removed and marked resolved
- **WHEN** the setting is on, one branch removes `tester`'s character and another changes it, git leaves
  `.troupe/actors/tester.md` unmerged, and the `troupe config set` that resolves config removes the character
- **THEN** the file is removed, and git's index has no entry for it

#### Scenario: Only the rewritten paths are staged
- **WHEN** the setting is on, a merge stops with `.troupe/actors/tester.yaml` conflicted, `.troupe/actors/tester.md`
  merged cleanly and a source file unmerged, and a person runs `troupe sync`
- **THEN** only `.troupe/actors/tester.yaml` is marked resolved
- **AND** the index entries of `.troupe/actors/tester.md`, the source file and troupe's event segments are unchanged

#### Scenario: Unmerged, but already what config writes
- **WHEN** the setting is on, git left `.troupe/actors/tester.yaml` unmerged, the person ran `git checkout --ours` on
  it, and that version is what the merged config writes
- **THEN** syncing writes nothing, and the path is still unmerged

#### Scenario: A rehearsal
- **WHEN** the setting is on, git left `.troupe/actors/tester.yaml` conflicted, and a person runs `troupe sync
  --rehearse`
- **THEN** the output says it would be rewritten and marked resolved
- **AND** nothing is written and the index is unchanged

### Requirement: Policy can forbid marking a file resolved
The policy setting `allow_mark_merges_resolved`, true by default, SHALL decide whether troupe may mark a file resolved.
When it's false and the setting is on, troupe SHALL act as if the setting were off, and the notice SHALL say that
policy forbade it, naming the policy variable.

#### Scenario: Forbidden by policy
- **WHEN** `TROUPE_SETTING_MARK_MERGES_RESOLVED` is `true`, `TROUPE_POLICY_ALLOW_MARK_MERGES_RESOLVED` is `false`, git
  left `.troupe/actors/tester.yaml` conflicted from two versions troupe wrote, and a person runs `troupe sync`
- **THEN** the file is rewritten and its bytes kept, as with the setting off, and git still shows it as unmerged
- **AND** the notice says to `git add` it, and that policy forbade troupe doing it, naming
  `TROUPE_POLICY_ALLOW_MARK_MERGES_RESOLVED`

### Requirement: A file with a side troupe didn't write is never marked resolved
A config file that is replaced while one of its unmerged sides isn't a version troupe wrote, such as one replaced with
`--force`, SHALL NOT be marked resolved, whatever the setting says.

#### Scenario: Forced past a hand-edited side
- **WHEN** the setting is on, git left `.troupe/actors/tester.yaml` conflicted with one side edited by hand, and a
  person runs `troupe sync --force`
- **THEN** the file is replaced and its bytes kept, and git still shows it as unmerged

### Requirement: Runtime files are a known kind
`.troupe/runtimes/<name>.yaml` SHALL be a kind in the registry of file kinds. Any other file in `.troupe/runtimes/`
SHALL be refused when syncing with `config.unknown-file`, as in any config directory.

#### Scenario: A stray file
- **WHEN** `.troupe/runtimes/notes.txt` exists and a person runs `troupe sync`
- **THEN** it is refused with `config.unknown-file`, naming the file

## REMOVED Requirements

### Requirement: Flush makes the files what config says
**Reason**: `troupe sync` replaces `troupe flush` (owner, 2026-11-21), and a deleted file is now a removal, not
written again (spec: config-hand-edits).
**Migration**: "Sync makes the files say what config says". Run `troupe sync` where `troupe flush` was run.

### Requirement: Only a file troupe wrote is replaced
**Reason**: the sweep reads a hand-edited file into config before anything is written, so a valid hand edit is no
longer refused, and an older version troupe wrote is read as an edit (owner, 2026-11-21).
**Migration**: "A file troupe can't read is never replaced" keeps the refusal for files troupe can't read, and its
conflict scenarios.

### Requirement: Only an explicit command rewrites a file git merged
**Reason**: renamed to say `troupe sync`, since a scenario's name named `troupe flush`.
**Migration**: "Only sync or a resolving change rewrites a file git merged", with the same rule.
