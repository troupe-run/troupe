# plugin-sdk: delta

## ADDED Requirements

### Requirement: The SDK never repeats a refused endpoint
When the SDK refuses a message because a field holding an endpoint doesn't match the endpoint pattern, its protocol
error SHALL name the field and say what an endpoint must be, and SHALL hold no part of the value, since the value may
hold user info such as a password. Every runner built on the SDK SHALL refuse it this way without code of its own.

#### Scenario: An endpoint with a password in run start
- **WHEN** the SDK parses a `run/start` whose `runtime.endpoint` is `https://user:<canary>@example.com/v1`
- **THEN** it raises a protocol error naming `runtime.endpoint` and saying an endpoint has no user info, and the error
  holds neither the canary nor `example.com`

#### Scenario: Another pattern-checked field
- **WHEN** the SDK parses a `run/start` whose `runId` isn't a UUID
- **THEN** its error still shows the value, as it does today

### Requirement: The SDK defines which credentials can be sent
The SDK SHALL define, once, which credential values can be sent in a request header: those whose every character is
visible ASCII (`!` to `~`). Core and every runner that sends a credential SHALL refuse one by that definition, each
in its own words, and never show the value.

#### Scenario: A non-ASCII character
- **WHEN** the SDK judges `sk-test-€abcdefgh`
- **THEN** it can't be sent

#### Scenario: Whitespace or a control character
- **WHEN** the SDK judges a value holding a space, a tab, `\r`, `\n` or `\x7f`
- **THEN** it can't be sent

#### Scenario: A typical key
- **WHEN** the SDK judges `sk-test-q7ZxW9pL4vR2`
- **THEN** it can be sent
