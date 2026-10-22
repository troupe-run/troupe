# config-files Specification

## Purpose

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
key, both naming its kind's schema at troupe.run by major version.

#### Scenario: An actor file names its schema
- **WHEN** an actor file is written
- **THEN** its first line is the language-server comment and its first key is `$schema`, both naming
  `https://troupe.run/protocol/0/config/actor.schema.json`

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
troupe wrote, by hash. Any other file SHALL be refused with `config.file-not-troupes`, naming the file and the fix,
and nothing SHALL be written.

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
- **THEN** it is refused with `config.file-not-troupes`, saying the file has git's conflict markers in it, and that
  the fix is to take one side with `git checkout --ours`, resolve, then `git add` the file and commit the merge
- **AND** after `git checkout --ours .troupe/actors/tester.md`, the same command is accepted and writes the file

#### Scenario: A clean merge of two branches' files
- **WHEN** git merges two branches' changes to `.troupe/actors/tester.yaml` without a conflict, giving exactly what
  the merged config would write
- **THEN** flushing leaves the file as it is

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
