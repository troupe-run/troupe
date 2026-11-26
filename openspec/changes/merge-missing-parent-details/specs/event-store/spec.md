## MODIFIED Requirements

### Requirement: A missing parent is refused
An event that names a parent which is not present SHALL make reads of its stream fail with an error that names the
file holding the event, the missing parent, and the fix: restore the removed file, or remove the dependent one too.

#### Scenario: A parent's file was removed by hand
- **WHEN** the segment holding an event is deleted while a later event in another segment names it as a parent
- **THEN** reading that stream fails with an error naming the later event's file and the missing parent ID
- **AND** the fix says to restore the removed file or remove the dependent one

#### Scenario: A config event's parent was removed by hand
- **WHEN** the segment holding a config event is deleted while a later config event names it as a parent, and config
  is read
- **THEN** the read fails with `events.missing-parent`, naming the later event's file, its line, its ID and the missing
  parent ID, as the protocol's details for that code require
