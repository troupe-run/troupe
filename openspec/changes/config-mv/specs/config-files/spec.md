## ADDED Requirements

### Requirement: A rename moves an entity's files as they are
When config renames an entity, the sync SHALL write the new name's files with the old files' bytes, changing only the
values the rename's change sets, and SHALL remove the old files. A person's formatting, comments and line endings in
a moved file SHALL be kept.

#### Scenario: A hand-formatted actor renamed
- **WHEN** `.troupe/actors/tester.yaml` holds comments and a key order of the person's, and they run `troupe config mv
  actors.tester actors.qa`
- **THEN** `.troupe/actors/qa.yaml` holds exactly the bytes `tester.yaml` held, `.troupe/actors/qa.md` exactly those
  of `tester.md`, and both `tester` files are gone

#### Scenario: A runtime renamed under its actors
- **WHEN** a person runs `troupe config mv runtimes.gpu-box runtimes.gpu`, and `.troupe/actors/tester.yaml` names
  `runtime: gpu-box` among lines of the person's
- **THEN** `.troupe/runtimes/gpu.yaml` holds the bytes `gpu-box.yaml` held, and in `tester.yaml` only the `runtime`
  line changes
