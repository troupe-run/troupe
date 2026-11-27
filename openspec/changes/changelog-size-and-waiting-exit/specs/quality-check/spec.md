## ADDED Requirements

### Requirement: The size gate doesn't measure generated changelogs
The size gate SHALL NOT measure a `CHANGELOG.md` anywhere in the repository. release-please writes them, every release
makes them larger, and nobody edits them by hand. `quality-gates.toml` SHALL exclude them with `**/CHANGELOG.md` in
`[size] exclude`, beside fixtures, archived changes and `uv.lock`.

#### Scenario: A release grows core's changelog past the limit
- **WHEN** a release pull request grows `packages/troupe/CHANGELOG.md` from 48,910 to 49,990 bytes
- **THEN** the size gate passes, and doesn't name the file

#### Scenario: Other Markdown is still measured
- **WHEN** a change grows `contributing/releasing.md` past 49,152 bytes, and it has no ceiling of its own
- **THEN** the size gate fails, naming the file
