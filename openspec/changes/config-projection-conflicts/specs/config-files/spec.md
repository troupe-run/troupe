## MODIFIED Requirements

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

## ADDED Requirements

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
change writes that file. Every other command that uses config SHALL refuse it with `config.file-not-troupes`, saying
the file is a merge of versions troupe wrote and that `troupe flush` rewrites it from the merged config, keeping a
copy. So a file a person is resolving is never changed by a command they ran for something else.

#### Scenario: Another command refuses it and names flush
- **WHEN** git left `.troupe/actors/tester.yaml` conflicted, config has no conflict, and a person runs `troupe
  perform tester`
- **THEN** it is refused with `config.file-not-troupes`, saying the file is a merge of versions troupe wrote and that
  `troupe flush` rewrites it from the merged config, keeping a copy
- **AND** the file is unchanged, and the run doesn't start

#### Scenario: A config set that doesn't write the file
- **WHEN** git left `.troupe/actors/tester.md` conflicted, and a person runs `troupe config set
  actors.reviewer.runner=scripted`
- **THEN** it is refused with `config.file-not-troupes`, naming `troupe flush`
- **AND** nothing is recorded or written
