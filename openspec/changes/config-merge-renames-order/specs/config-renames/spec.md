## MODIFIED Requirements

### Requirement: Renames that can't both hold are a conflict
Two lines renaming one entity to different names, one renaming an entity while the other removes it, or one renaming
an entity onto a name the other made SHALL be a conflict between the changes, shown and resolved like any other.

#### Scenario: Two renames
- **WHEN** one branch renames `tester` to `qa`, another renames it to `reviewer`, and they are merged
- **THEN** the two changes are in conflict on `actors.tester`, and config shows `tester` under its name from before
  the split

#### Scenario: The same rename on both branches
- **WHEN** two branches each rename `tester` to `qa`, and they are merged
- **THEN** config has `qa`, with no conflict

#### Scenario: A rename and a removal
- **WHEN** one branch renames `tester` to `qa`, another removes `tester`, and they are merged
- **THEN** the two changes are in conflict

#### Scenario: A rename onto a name made on another branch
- **WHEN** one branch renames `tester` to `qa`, another makes a new actor `qa`, and they are merged
- **THEN** the rename and the changes that made the other `qa` are in conflict on `actors.qa`

#### Scenario: A rename left out falls back to what its history says
- **WHEN** a rename onto a name made on another branch is left out, and the entity's earlier history holds a rename
  and a removal from two branches
- **THEN** the entity falls back to the name that history works out (here, its name from before them), and config
  is the same whatever order the events are read in

#### Scenario: Resolving two renames with a rename
- **WHEN** config has the conflict of two renames of `tester`, and a person runs `troupe config mv actors.tester
  actors.qa`
- **THEN** the change is recorded, and config has `qa` and no conflict
