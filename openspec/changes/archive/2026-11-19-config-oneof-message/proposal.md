# Proposal

## Why

When a value in an actor's options fails every branch of a `oneOf` in the runner's options schema, config's error
gives the `oneOf`'s description instead of what's wrong. A scripted step `{"event": {"type": "init", "runner": "x"}}`
is refused with "it doesn't fit the scripted runner's options schema: An object with exactly one key, the step's
kind..", although the step has exactly one key. What's actually wrong is inside the `init` event: `tools` is missing
and `runner` isn't an object. The message points the reader at the wrong fix and ends with two full stops. Found
while checking the 0.2.0 docs (#425); tracked as troupe-run/troupe#453.

## What Changes

- When an object fails every branch of a `oneOf` or `anyOf`, config drops the branches the object plainly isn't (one
  that doesn't define a key the object holds, one whose `const` field, such as an event's `type`, differs, or one
  that takes another type). When exactly one branch is left, the error names that branch's own failures, each at
  its own path and in the words config already uses (a required field, a field's type, a value outside a list).
  This applies at every level, so a step's event is followed into the event's own `oneOf`.
- When no branch or several are left, or the value isn't an object, the error gives the description, as today.
  Scalar alternatives such as Ollama's `think` (a boolean, or `low`, `medium` or `high`) are described better by
  their description than by one branch.
- A rule that ends with a schema's description no longer gets a second full stop.
- The refused value is still repeated nowhere: a branch's failures are worded by the same code as any other rule.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `config`: "Values are checked before a change is recorded" says that when an object fits none of a schema's
  alternatives and one is closest, the error names what's wrong in that one, with a scenario using the issue's
  script.

## Impact

- `packages/troupe/src/troupe/core/config/kinds.py`: `_schema_problems` expands a `oneOf`/`anyOf` error into the
  closest branch's errors; `_rule` stops the doubled full stop.
- `packages/troupe/tests/test_config_kinds.py`: tests with the issue's input, a scalar `oneOf`, and the fallbacks.
- Any runner's options schema, and config's own schemas, get the same treatment: nothing is specific to the scripted
  runner. No schema, protocol or error-code change.
