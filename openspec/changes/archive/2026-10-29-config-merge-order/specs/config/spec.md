# Spec Delta

## MODIFIED Requirements

### Requirement: A merge combines each line's net change
When the config stream has more than one head, config SHALL be worked out from both lines of history: for each
value, each line's net change since the lines split, from its first `before` to its last `after`. A line whose net
change ends where it began SHALL count as not changing the value. A line whose first changes to the value start from
different values SHALL count as changing it.

#### Scenario: Two branches change different actors
- **WHEN** one branch sets a value of `reviewer`, another sets a value of `tester`, and they are merged
- **THEN** config holds both changes, with no conflict

#### Scenario: A change and a change back
- **WHEN** one branch changes `tester`'s character and changes it back, another changes it to new text, and they
  are merged
- **THEN** config holds the new text, with no conflict

#### Scenario: Two branches make the same change
- **WHEN** two branches each set `actors.tester.runner` to `claude-code`, and are merged
- **THEN** config holds `claude-code`, with no conflict

#### Scenario: Every clone agrees
- **WHEN** the same branches' events reach two clones in different orders
- **THEN** both clones work out the same config and the same conflicts

#### Scenario: A line whose first changes start from different values is a change
- **WHEN** one branch changes `tester`'s character from new text to other text, and another line of history holds two
  concurrent changes to it, one from that new text and one from another value, which a settle joins, and the line
  ends at the new text
- **THEN** the two lines are in conflict, whatever order the events arrived in

## ADDED Requirements

### Requirement: The history before the lines works out a value no line's change is left at
Where no line's change is left at a value, because the lines conflict or every one counts as not changing it, the
history before those lines SHALL work the value out by the same rule, never the order the events arrived in.

#### Scenario: A conflict after a settle shows the value the settle left
- **WHEN** two branches set `tester`'s character, one changing it to new text and the other changing it to other text
  and back, a write settles them, and two branches from the settle then set it to different text
- **THEN** the two later changes are in conflict, and config shows the new text the settle left, whatever order the
  events arrived in

#### Scenario: Lines after a settle that change a value back leave the value the settle left
- **WHEN** two branches set `tester`'s character, one changing it to new text and the other changing it to other text
  and back, a write settles them, and two branches from the settle each change it and change it back
- **THEN** config holds the new text the settle left, with no conflict, whatever order the events arrived in
