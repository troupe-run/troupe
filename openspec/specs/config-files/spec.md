# config-files Specification

## Purpose

Capability: `cap:config`, `cap:projections`

Projects a theatre's config to files under `.troupe/` that a person can read and review as diffs, never losing a
file a person wrote, and keeps the theatre's own git files holding what troupe needs.

## Requirements

### Requirement: Each actor is projected to its own files
Each actor in config SHALL be written to `.troupe/actors/<name>.yaml`, and its character, when it has one, to
`.troupe/actors/<name>.md`, whose whole content is the character's text. An actor with no character SHALL have no
`.md` file.

#### Scenario: An actor with a character
- **WHEN** config has the actor `tester` with a runner, an effect check and a character
- **THEN** `.troupe/actors/tester.yaml` holds the runner and the effect check
- **AND** `.troupe/actors/tester.md` holds the character's text, byte for byte

#### Scenario: A removed actor
- **WHEN** `tester` is removed from config
- **THEN** its `.yaml` and `.md` files are removed

### Requirement: Each config file names its schema twice
Each YAML config file SHALL begin with a `# yaml-language-server: $schema=<url>` comment and a `$schema: <url>`
key, both naming its kind's schema at troupe.run by the major version of the protocol troupe carries.

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

### Requirement: Flush makes the files what config says
`troupe flush` SHALL make every config file exactly what config would write, adding, replacing and removing files,
and SHALL report each file it changed and why. Every command that uses config SHALL flush first, and SHALL stop if
the flush is refused.

#### Scenario: A deleted file is written again
- **WHEN** a person deletes `.troupe/actors/tester.yaml` and runs `troupe flush`
- **THEN** the file is written again from config, with a notice naming it

#### Scenario: Perform flushes first
- **WHEN** `.troupe/actors/tester.yaml` is missing and a person runs `troupe perform tester`
- **THEN** the file is written before the run starts

#### Scenario: Nothing to do
- **WHEN** every config file is already what config would write
- **THEN** `troupe flush` changes nothing and says so

### Requirement: Only a file troupe wrote is replaced
Before replacing or removing a file, troupe SHALL check that its bytes are what config would write now, or a version
troupe wrote, by hash, or that git merged it from versions troupe wrote. Any other file SHALL be refused with
`config.file-not-troupes`, naming the file and the fix, and nothing SHALL be written.

#### Scenario: A file edited by hand
- **WHEN** a person edits `.troupe/actors/tester.yaml` and runs `troupe config set actors.tester.runner=scripted`
- **THEN** it is refused with `config.file-not-troupes`, naming the file and saying to undo the edit or run `troupe
  flush --force`
- **AND** nothing is recorded or written

#### Scenario: An older version troupe wrote
- **WHEN** a person restores `.troupe/actors/tester.yaml` from an earlier commit and runs `troupe flush`
- **THEN** the file is written again from config, with a notice naming it

#### Scenario: A file git left conflicted
- **WHEN** git merges two branches that changed `.troupe/actors/tester.md`, leaves its conflict markers in the file,
  and a person runs `troupe config set actors.tester.character=Both.`
- **THEN** the command is accepted, and `.troupe/actors/tester.md` holds `Both.`
- **AND** a `config.merge-rewritten` notice names the file and the hash its conflicted bytes are kept under

#### Scenario: A conflicted file with a side troupe didn't write
- **WHEN** one branch's `.troupe/actors/tester.yaml` was edited by hand and committed, git merges it with another
  branch's change to the file and leaves it conflicted, and a person runs `troupe flush`
- **THEN** it is refused with `config.file-not-troupes`, saying the file has git's conflict markers in it, naming the
  side troupe didn't write, and saying to take the side troupe wrote with `git checkout --ours` or `--theirs`, or to
  run `troupe flush --force`
- **AND** nothing is written

#### Scenario: A clean merge of two branches' files
- **WHEN** git merges two branches' changes to `.troupe/actors/tester.yaml` without a conflict, giving exactly what
  the merged config would write
- **THEN** flushing leaves the file as it is

### Requirement: A file git merged from troupe's versions is rewritten from the merged config
A config file SHALL count as merged from troupe's versions when git left it unmerged, or merged it cleanly in the merge
in progress or in HEAD's merge commit, and every side it came from is a version troupe recorded. When rewriting one,
troupe SHALL write or remove it as the merged config says, keep its bytes in the artifact store first, and report
`config.merge-rewritten` naming the file, the kept hash, and that the person must `git add` it. troupe SHALL NOT
change git's index.

#### Scenario: Config merged cleanly but the file conflicted
- **WHEN** one branch sets `actors.tester.runner` and another sets one of `tester`'s options, git leaves
  `.troupe/actors/tester.yaml` conflicted, and a person runs `troupe flush`
- **THEN** the file is what the merged config writes, holding both branches' changes
- **AND** the notice names the file and its kept hash, and says to `git add` it and commit the merge
- **AND** git still shows the file as unmerged

#### Scenario: A config conflict and a conflicted file
- **WHEN** two branches set `actors.tester.character` to different text, git leaves `.troupe/actors/tester.md`
  conflicted, and a person runs `troupe config set actors.tester.character=Both.`
- **THEN** the config conflict is resolved and the file holds `Both.`
- **AND** the conflicted bytes are kept, and the notice names their hash

#### Scenario: A resolution started by hand is kept
- **WHEN** git left `.troupe/actors/tester.md` conflicted, the person deleted some of the markers by hand, and runs
  `troupe flush`
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
- **WHEN** git merged `.troupe/actors/tester.md` cleanly, the person then edited the file, and runs `troupe flush`
- **THEN** it is refused with `config.file-not-troupes`, as any hand edit is

#### Scenario: A merge older than HEAD
- **WHEN** git merged `.troupe/actors/tester.md` cleanly in a merge commit that has commits after it, and the file
  isn't a version troupe wrote
- **THEN** flushing refuses it with `config.file-not-troupes`

#### Scenario: A rehearsal
- **WHEN** git left `.troupe/actors/tester.yaml` conflicted, and a person runs `troupe flush --rehearse`
- **THEN** the output names the file and says it would be rewritten because git merged it from versions troupe
  wrote
- **AND** nothing is written or kept

#### Scenario: Without git
- **WHEN** the theatre uses the plain filesystem adapter and `.troupe/actors/tester.yaml` holds conflict markers
- **THEN** flushing refuses it with `config.file-not-troupes`, as any file troupe didn't write is

### Requirement: Only an explicit command rewrites a file git merged
A file merged from troupe's versions SHALL be rewritten only by `troupe flush`, or by a `troupe config set` whose
change writes that file or resolves config's conflicts. Any other command that uses config SHALL refuse it with
`config.file-not-troupes`, saying that `troupe flush` rewrites it from the merged config, keeping a copy.

#### Scenario: Another command refuses it and names flush
- **WHEN** git left `.troupe/actors/tester.yaml` conflicted, config has no conflict, and a person runs `troupe
  perform tester`
- **THEN** it is refused with `config.file-not-troupes`, saying the file is a merge of versions troupe wrote and that
  `troupe flush` rewrites it from the merged config, keeping a copy
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
- **THEN** it is refused with `config.file-not-troupes`, naming `troupe flush`
- **AND** nothing is recorded or written

### Requirement: Force replaces a file and keeps a copy
`troupe flush --force` SHALL replace files that aren't troupe's, first storing each one's bytes in the artifact store
and naming each file and the hash it was kept under.

#### Scenario: Forcing past a hand edit
- **WHEN** a person runs `troupe flush --force` after editing `.troupe/actors/tester.yaml` by hand
- **THEN** the file is what config says
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
- **THEN** the next flush removes it, and config is unchanged

### Requirement: Config writes queue
Flushes and config changes SHALL hold a lock for the whole of staging, recording and replacing, so two commands
writing config files never interleave. A wait SHALL be announced and bounded.

#### Scenario: Two terminals
- **WHEN** two `troupe config set` commands run at once in one theatre
- **THEN** one waits, says it is waiting, and runs after the other has replaced its files

### Requirement: Files in config directories are known kinds
Every file in a config directory SHALL match a kind in the registry of file kinds, be a staged write, or be a named
operating-system file. Any other file SHALL be refused when flushing, with `config.unknown-file`, naming it.
`events/`, `local/`, `.gitignore`, `.gitattributes` and `troupe.yaml` SHALL be reserved and never config.

#### Scenario: A stray file
- **WHEN** `.troupe/actors/notes.txt` exists and a person runs `troupe flush`
- **THEN** it is refused with `config.unknown-file`, naming the file

#### Scenario: Finder's metadata
- **WHEN** `.troupe/actors/.DS_Store` exists
- **THEN** flushing ignores it

### Requirement: The theatre's git files hold what troupe needs
Whenever troupe writes into `.troupe/`, `.gitignore` SHALL hold `local/` and `.*.troupe~`, and `.gitattributes` SHALL
hold `events/** -text` and `actors/** -text`. A missing pattern SHALL be appended under a comment saying troupe
added it and why. A line already there SHALL never be changed, moved or removed.

#### Scenario: An existing gitignore
- **WHEN** `.troupe/.gitignore` holds `local/` and a person's own line, and troupe writes config
- **THEN** `.*.troupe~` is appended under troupe's comment
- **AND** the two lines that were there are unchanged and in place

#### Scenario: Line endings on Windows
- **WHEN** a theatre with config files is cloned on Windows with `core.autocrlf` set
- **THEN** the config files keep the line endings troupe wrote, so their hashes match
