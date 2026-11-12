## REMOVED Requirements

### Requirement: Claude Code's automatic compaction is off
**Reason**: A run told `compact` now lets Claude Code compact, so compaction is off only by default.
**Migration**: Replaced by "Claude Code compacts only when the run says compact", which keeps it off for every run
told `fail`, whatever its options.

## ADDED Requirements

### Requirement: Claude Code compacts only when the run says compact
The runner SHALL set `autoCompactEnabled` in the settings file it gives Claude Code with `--settings`: `true` when the
run's `onContextFull` is `compact`, and `false` otherwise, whatever its options. When it's `compact`, the runner SHALL
leave `DISABLE_AUTO_COMPACT` out of Claude Code's environment, and when it was set, send a `log` event at level
`warning` naming it.

#### Scenario: A run told fail
- **WHEN** a run starts with `onContextFull` `fail` and no options
- **THEN** the settings file Claude Code is given with `--settings` holds `autoCompactEnabled` `false`

#### Scenario: A run told fail that loads project settings
- **WHEN** a run starts with `onContextFull` `fail` and `settingSources` `["project"]`
- **THEN** the settings file Claude Code is given with `--settings` still holds `autoCompactEnabled` `false`

#### Scenario: A run told compact
- **WHEN** a run starts with `onContextFull` `compact`
- **THEN** the settings file holds `autoCompactEnabled` `true`

#### Scenario: A person's variable that would turn it off
- **WHEN** a run told `compact` starts in an environment with `DISABLE_AUTO_COMPACT` `1`
- **THEN** Claude Code's environment has no `DISABLE_AUTO_COMPACT`
- **AND** the run sends a `log` event at level `warning`, after `init`, naming `DISABLE_AUTO_COMPACT` and saying the
  actor's `onContextFull` overrides it

#### Scenario: A run told compact with no such variable
- **WHEN** a run told `compact` starts in an environment without `DISABLE_AUTO_COMPACT`
- **THEN** no `log` event names `DISABLE_AUTO_COMPACT`

### Requirement: Claude Code's compaction is a context event
A `system` record with subtype `compact_boundary` SHALL map to a `context` event with `kind` `compacted` and `by`
`engine`, carrying `tokensBefore` from its `compact_metadata.pre_tokens` when that is a whole number of zero or more.
`system` records with status `compacting` or a `compact_result` SHALL map to debug `log` events, not `context` events.

#### Scenario: A compaction that succeeds
- **WHEN** the `compaction-proactive` fixture plays
- **THEN** the runner sends one `context` event with `kind` `compacted`, `by` `engine` and `tokensBefore` from the
  boundary record, before the events of the turn that follows it, and the run ends `ok`

#### Scenario: A compaction after a refusal
- **WHEN** the `compaction-reactive` fixture plays: the API refuses a request as too long, and Claude Code compacts
- **THEN** the runner sends one `context` event with `kind` `compacted` and `by` `engine`, and the run ends `ok`

#### Scenario: A compaction that fails
- **WHEN** a run's records show status `compacting`, then a `compact_result` of `failed`, then a result record with
  `terminal_reason` `blocking_limit`
- **THEN** no `context` event is sent, and the run ends with `error` and `reason` `context-length`

#### Scenario: A compaction the run didn't ask for
- **WHEN** a run told `fail` receives a `compact_boundary` record
- **THEN** the runner still sends a `context` event for it

### Requirement: The capture tool records compaction fixtures only when Claude Code compacted
The capture tool SHALL capture compaction fixtures through the runner's own command with `onContextFull` `compact`,
against a stand-in API that answers Claude Code's compaction request with a summary. It SHALL refuse to write one
unless it saw a `compact_boundary` record.

#### Scenario: No compaction seen
- **WHEN** a compaction capture ends without a `compact_boundary` record
- **THEN** the tool writes no fixture, and says compaction wasn't seen
