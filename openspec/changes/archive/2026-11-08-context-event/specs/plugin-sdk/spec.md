## ADDED Requirements

### Requirement: The SDK builds a context event fitted to the run's limits
The SDK SHALL give a runner one call that builds a `context` event from its kind, who lost the content, a message and
the amounts it knows: numbered by the run's event counter, with the message cut to fit the run's summary limit and
maximum event size, and the unknown amounts left out.

#### Scenario: A compaction with only the size before
- **WHEN** a runner asks the SDK for a `context` event with kind `compacted`, by `engine`, a message and 41000 tokens
  before
- **THEN** the event takes the next `seq` from the run's counter, validates against the contract's schema, and carries
  `tokensBefore` 41000 and no other count

#### Scenario: A message longer than the summary limit
- **WHEN** a runner asks the SDK for a `context` event whose message is larger than the run's summary limit
- **THEN** the event's message is cut on a character boundary to fit, saying how many bytes were left out, and the
  whole event is within the run's maximum event size

#### Scenario: A kind off the list
- **WHEN** a runner asks the SDK for a `context` event whose kind is not `compacted`, `truncated` or `other`
- **THEN** the SDK raises a protocol error naming the kind, and the counter's next `seq` is unchanged
