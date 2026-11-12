## ADDED Requirements

### Requirement: The SDK chooses which tool results a runner removes
The SDK SHALL give a runner that holds its conversation one call that chooses which tool results to replace with a
stub to bring an estimated size down to a target, oldest first. It SHALL never choose a result of the latest turn,
one already stubbed, or one no larger than its stub, and SHALL choose none when that can't help.

#### Scenario: Oldest first, up to the target
- **WHEN** a runner offers five results of 10 KB each, the last one in the latest turn, with an estimate 25 KB over
  its target
- **THEN** the SDK chooses the first three, in order, and not the fifth

#### Scenario: Only the latest turn's results
- **WHEN** every result a runner offers is in the latest turn
- **THEN** the SDK chooses none

#### Scenario: Any offer
- **WHEN** a property test offers any list of results, estimate and target
- **THEN** the SDK never chooses a protected result, and chooses no more results once the estimate is at or below the
  target

### Requirement: The SDK words the stub that replaces a tool result
The SDK SHALL give the text that replaces a removed tool result, one wording for every runner. It SHALL name the tool,
say the result was removed to make room in the context window, and say to call the tool again if it's still needed.

#### Scenario: A removed Read
- **WHEN** a runner asks the SDK for the stub of a `Read` result
- **THEN** the text names `Read`, says it was removed to make room in the context window, and says to call `Read`
  again if it's still needed

### Requirement: The SDK estimates a conversation's tokens from its bytes
The SDK SHALL estimate a conversation's tokens from its size in bytes at a named default rate, and SHALL calibrate
the rate from the last request whose input tokens the engine reported, using that request's size.

#### Scenario: Before any reported count
- **WHEN** a runner asks for an estimate before any request has been answered
- **THEN** the estimate uses the SDK's named default bytes per token

#### Scenario: After a reported count
- **WHEN** the engine reported 1000 input tokens for a request of 4000 bytes
- **THEN** the SDK estimates a conversation of 8000 bytes as 2000 tokens
