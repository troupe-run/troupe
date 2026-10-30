# Spec Delta

## MODIFIED Requirements

### Requirement: A file git merged from troupe's versions is rewritten from the merged config
A config file SHALL count as merged from troupe's versions when git left it unmerged, or merged it cleanly in the merge
in progress or in HEAD's merge commit, and every side it came from is a version troupe recorded. When rewriting one,
troupe SHALL write or remove it as the merged config says, keep its bytes in the artifact store first, and report
`config.merge-rewritten` naming the file, the kept hash, and whether troupe marked it resolved in git's index.

#### Scenario: Config merged cleanly but the file conflicted
- **WHEN** one branch sets `actors.tester.runner` and another sets one of `tester`'s options, git leaves
  `.troupe/actors/tester.yaml` conflicted, and a person runs `troupe flush`
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

## ADDED Requirements

### Requirement: A rewritten unmerged file is marked resolved when the setting is on
When the setting `mark_merges_resolved` is true and policy allows it, each config file a command writes or removes
whose path git's index holds unmerged, and whose every side is a version troupe wrote, SHALL be marked resolved in the
index, staging the bytes troupe wrote or the removal. Nothing else SHALL be staged. When the setting is false, its
default, the index SHALL be left alone.

#### Scenario: Marked resolved
- **WHEN** `TROUPE_SETTING_MARK_MERGES_RESOLVED` is `true`, git left `.troupe/actors/tester.yaml` conflicted from two
  versions troupe wrote, and a person runs `troupe flush`
- **THEN** the file is what the merged config writes, and git's index holds exactly those bytes for it, with no
  unmerged entry
- **AND** the `config.merge-rewritten` notice says troupe marked it resolved, and that the merge can be committed

#### Scenario: Removed and marked resolved
- **WHEN** the setting is on, one branch removes `tester`'s character and another changes it, git leaves
  `.troupe/actors/tester.md` unmerged, and the `troupe config set` that resolves config removes the character
- **THEN** the file is removed, and git's index has no entry for it

#### Scenario: Only the rewritten paths are staged
- **WHEN** the setting is on, a merge stops with `.troupe/actors/tester.yaml` conflicted, `.troupe/actors/tester.md`
  merged cleanly and a source file unmerged, and a person runs `troupe flush`
- **THEN** only `.troupe/actors/tester.yaml` is marked resolved
- **AND** the index entries of `.troupe/actors/tester.md`, the source file and troupe's event segments are unchanged

#### Scenario: Unmerged, but already what config writes
- **WHEN** the setting is on, git left `.troupe/actors/tester.yaml` unmerged, the person ran `git checkout --ours` on
  it, and that version is what the merged config writes
- **THEN** flushing writes nothing, and the path is still unmerged

#### Scenario: A rehearsal
- **WHEN** the setting is on, git left `.troupe/actors/tester.yaml` conflicted, and a person runs `troupe flush
  --rehearse`
- **THEN** the output says it would be rewritten and marked resolved
- **AND** nothing is written and the index is unchanged

### Requirement: Policy can forbid marking a file resolved
The policy setting `allow_mark_merges_resolved`, true by default, SHALL decide whether troupe may mark a file resolved.
When it's false and the setting is on, troupe SHALL act as if the setting were off, and the notice SHALL say that
policy forbade it, naming the policy variable.

#### Scenario: Forbidden by policy
- **WHEN** `TROUPE_SETTING_MARK_MERGES_RESOLVED` is `true`, `TROUPE_POLICY_ALLOW_MARK_MERGES_RESOLVED` is `false`, git
  left `.troupe/actors/tester.yaml` conflicted from two versions troupe wrote, and a person runs `troupe flush`
- **THEN** the file is rewritten and its bytes kept, as with the setting off, and git still shows it as unmerged
- **AND** the notice says to `git add` it, and that policy forbade troupe doing it, naming
  `TROUPE_POLICY_ALLOW_MARK_MERGES_RESOLVED`

### Requirement: A file with a side troupe didn't write is never marked resolved
A config file that is replaced while one of its unmerged sides isn't a version troupe wrote, such as one replaced with
`--force`, SHALL NOT be marked resolved, whatever the setting says.

#### Scenario: Forced past a hand-edited side
- **WHEN** the setting is on, git left `.troupe/actors/tester.yaml` conflicted with one side edited by hand, and a
  person runs `troupe flush --force`
- **THEN** the file is replaced and its bytes kept, and git still shows it as unmerged

### Requirement: Marking resolved stages only what troupe saw and wrote
troupe SHALL mark a path resolved only while git's index still holds the sides the command checked, and SHALL stage the
bytes troupe wrote, not whatever the file holds by then. When the index has changed, or git fails to mark it, the file
SHALL stay written and its bytes kept, and the notice SHALL say it wasn't marked and why.

#### Scenario: The index moved
- **WHEN** the setting is on, and the person resolves `.troupe/actors/tester.yaml` in git themselves after troupe read
  the index but before it marked the path
- **THEN** troupe leaves the path's index entry as the person left it
- **AND** the notice says the index changed, so troupe didn't mark it

#### Scenario: Edited as troupe wrote it
- **WHEN** the setting is on, and the file is changed on disk after troupe wrote it and before troupe marked it
- **THEN** the index holds the bytes troupe wrote, not the file's new bytes
