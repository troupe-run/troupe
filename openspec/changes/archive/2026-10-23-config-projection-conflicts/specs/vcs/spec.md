## ADDED Requirements

### Requirement: The VCS port reports a path's merge sides
The VCS port SHALL report, for theatre-relative paths, each one git left unmerged or merged cleanly in the merge in
progress or in HEAD's merge commit: each side's bytes (none for a side without the file), the bytes the merge gave,
and whether it was conflicted or clean. A path in no merge SHALL be left out. An adapter with no merges SHALL report
none.

#### Scenario: The plain filesystem adapter
- **WHEN** merge sides are asked for from the plain filesystem adapter
- **THEN** it reports none

### Requirement: The git adapter reads a conflicted path's sides from the index
For a path git's index holds unmerged, the git adapter SHALL report it as conflicted, with ours and theirs read from
the index's stages, byte for byte. A side the index has no stage for SHALL be reported as absent.

#### Scenario: Both branches changed the file
- **WHEN** a merge leaves `.troupe/actors/tester.yaml` with conflict markers
- **THEN** the adapter reports it conflicted, with each branch's version of the file as its sides

#### Scenario: Removed on one branch
- **WHEN** a merge stops because one branch removed `.troupe/actors/tester.md` and the other changed it
- **THEN** the adapter reports it conflicted, with ours absent and theirs the changed file

#### Scenario: A rebase stops on the file
- **WHEN** a rebase or cherry-pick stops with `.troupe/actors/tester.yaml` unmerged
- **THEN** the adapter reports it conflicted, with its sides from the index

### Requirement: The git adapter reports a clean merge only when it reproduces it
For a path that isn't unmerged, the git adapter SHALL report it as merged cleanly only during a merge in progress, or
when HEAD is a merge of two parents, and only when git, merging the two parents again, reproduces for that path, with
no conflict, exactly the bytes the merge gave. Otherwise it SHALL leave the path out.

#### Scenario: A clean merge in progress
- **WHEN** a merge stops on another file's conflict, and git merged `.troupe/actors/tester.md` cleanly
- **THEN** the adapter reports it merged cleanly, with HEAD's and the merged branch's versions as its sides, and
  the index's version as what the merge gave

#### Scenario: A committed clean merge
- **WHEN** HEAD is a merge commit in which git merged `.troupe/actors/tester.md` cleanly
- **THEN** the adapter reports it merged cleanly, with each parent's version as its sides

#### Scenario: A merge someone edited before committing it
- **WHEN** HEAD is a merge commit whose `.troupe/actors/tester.md` differs from the clean merge of its parents'
  versions
- **THEN** the adapter leaves the path out

#### Scenario: A merge of more than two parents
- **WHEN** HEAD is an octopus merge
- **THEN** the adapter reports no clean merges

#### Scenario: No merge
- **WHEN** no merge is in progress and HEAD has one parent
- **THEN** the adapter reports no clean merges
