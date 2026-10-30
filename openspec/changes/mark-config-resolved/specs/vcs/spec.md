# Spec Delta

## ADDED Requirements

### Requirement: The VCS port marks paths resolved
The VCS port SHALL mark theatre-relative paths resolved, given for each one the conflicted merge sides the caller read
and the bytes to stage, or none to stage its removal. It SHALL report, for each path, whether it was marked, and if
not, why. An adapter with no index SHALL mark none and say so.

#### Scenario: The plain filesystem adapter
- **WHEN** the plain filesystem adapter is asked to mark `.troupe/actors/tester.yaml` resolved
- **THEN** it marks nothing, and reports that it has no index

### Requirement: The git adapter stages exactly the given bytes
For a path still unmerged with the stages the caller read, the git adapter SHALL replace every unmerged entry with
one stage-0 entry holding the given bytes, stored as `git add` would store them, or SHALL remove every entry for the
path when no bytes are given. It SHALL NOT read the working file, and SHALL change no other path's entry.

#### Scenario: A conflicted file
- **WHEN** `.troupe/actors/tester.yaml` has stages 1, 2 and 3, and the adapter is asked to mark it resolved with
  bytes `B`
- **THEN** `git ls-files -s` lists one stage-0 entry for it whose blob is `B`, and `git ls-files -u` lists nothing
  for it
- **AND** a merge in progress can be committed without another `git add`

#### Scenario: A removal
- **WHEN** `.troupe/actors/tester.md` has stages 1 and 3, and the adapter is asked to mark it resolved with no bytes
- **THEN** the index has no entry for it

#### Scenario: The file changed on disk
- **WHEN** the working file holds bytes `C`, and the adapter is asked to mark it resolved with bytes `B`
- **THEN** the index holds `B`

### Requirement: The git adapter leaves a path whose stages have changed
The git adapter SHALL mark a path resolved only when the index still holds exactly the unmerged stages, modes and
objects, the caller read. Otherwise it SHALL leave the path's entries unchanged and report that the index changed.

#### Scenario: Already resolved by the person
- **WHEN** the adapter read `.troupe/actors/tester.yaml` as conflicted, and the person then ran `git add` on it
- **THEN** asking the adapter to mark it resolved leaves its entry as `git add` left it, and reports that the index
  changed

#### Scenario: Not unmerged any more
- **WHEN** the merge was aborted after the adapter read the path's sides
- **THEN** the adapter marks nothing, and reports that the index changed
