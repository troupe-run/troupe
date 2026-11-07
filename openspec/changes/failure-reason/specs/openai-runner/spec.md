## ADDED Requirements

### Requirement: Each failure reports its reason
Every `error` result the OpenAI runner sends SHALL carry the reason its failure maps to, from one table in the runner:
a refused credential `authentication`, out of quota `quota`, a too-long `Retry-After` `rate-limit`, a context-length
error `context-length`, a refusal or content filter `refused`, the output limit `output-limit`, the turn limit
`turn-limit`, the token budget `budget`, and retries run out the last retry's reason.

#### Scenario: A rejected credential
- **WHEN** the first request is answered 401
- **THEN** the run ends with an `error` result with `reason` `authentication`

#### Scenario: Out of quota
- **WHEN** a request is answered 429 with the error code `insufficient_quota`
- **THEN** the `result` has `reason` `quota`

#### Scenario: A wait longer than the cap
- **WHEN** a request is answered 429 with `Retry-After` an hour
- **THEN** the `result` has `reason` `rate-limit`

#### Scenario: The context is too long
- **WHEN** a request is answered 400 with the error code `context_length_exceeded`
- **THEN** the `result` has `reason` `context-length`

#### Scenario: A refusal
- **WHEN** a response's output message holds a refusal
- **THEN** the `result` has `reason` `refused`

#### Scenario: A content filter
- **WHEN** a response ends `incomplete` with reason `content_filter`
- **THEN** the `result` has `reason` `refused`

#### Scenario: The output limit
- **WHEN** a response ends `incomplete` with reason `max_output_tokens`
- **THEN** the `result` has `reason` `output-limit`

#### Scenario: The turn limit
- **WHEN** a run reaches `maxTurns` while the model is still calling tools
- **THEN** the `result` has `reason` `turn-limit`

#### Scenario: The token budget
- **WHEN** a run spends `maxTotalTokens` after a response that asks for a tool call
- **THEN** the `result` has `reason` `budget`

#### Scenario: Retries run out
- **WHEN** every attempt is answered 500
- **THEN** the `result` has `reason` `server`

### Requirement: An endpoint or service that can't serve the run is a configuration failure
A request redirected, or answered 404 without OpenAI's error shape, or refused with the error code `model_not_found`,
SHALL end the run with `reason` `configuration`: the runtime's endpoint or model is what needs changing.

#### Scenario: Nothing at the endpoint's path
- **WHEN** a request is answered 404 without OpenAI's error shape
- **THEN** the `result` has `reason` `configuration`

#### Scenario: A redirect
- **WHEN** a request is answered 301
- **THEN** the `result` has `reason` `configuration`

#### Scenario: A model the service doesn't have
- **WHEN** a request is answered 404 with the error code `model_not_found`
- **THEN** the `result` has `reason` `configuration`

### Requirement: Failures without an entry are engine, runner or other
A tool call the service sent without a `call_id` SHALL end with `reason` `engine`, the runner's own unexpected failure
with `runner`, and any other failure (another client error, a failed response whose code the runner doesn't name, an
unknown or other incomplete status) with `other`.

#### Scenario: A tool call without a call id
- **WHEN** a response holds a tool call with no `call_id`
- **THEN** the `result` has `reason` `engine`

#### Scenario: The runner fails
- **WHEN** the runner raises an exception it didn't expect during a run
- **THEN** the `result` has `reason` `runner`

#### Scenario: An unknown status
- **WHEN** a response ends with status `paused`
- **THEN** the `result` has `reason` `other`

#### Scenario: A failed response retrying can't fix
- **WHEN** a response ends `failed` with the code `invalid_prompt`
- **THEN** the `result` has `reason` `other`
