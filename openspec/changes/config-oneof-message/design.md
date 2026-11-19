# Design

## Context

`_schema_problems` in `core/config/kinds.py` turns each top-level `jsonschema` error into a `Problem`: a path, a rule
in words and a fix. A `oneOf` or `anyOf` error is worded by `_rule` as "it doesn't fit <schema>: <description>", and
`_refuse` adds a full stop after the rule. The branches' own errors sit unused in the error's `context`, each tagged
with its branch's index (`relative_schema_path[0]`) and carrying its own absolute path.

For the issue's step, the step's `oneOf` has thirteen branches. Branch 0 (`event`) fails only inside the event; each
of the other twelve fails `additionalProperties` (the step's `event` key isn't theirs). The event's `oneOf` has nine
branches. Branch 0 (`init`) fails `required: tools` and `type` on `runner`; each of the other eight fails
`additionalProperties` and `const` on `type`. `jsonschema.best_match` picks only `runner`'s type error, so it would
lose `tools`.

## Goals / Non-Goals

**Goals:**

- When an object fits no alternative, the error names what's wrong in the alternative it came closest to, using the
  issue's script as the test, written to fail on main first.
- One full stop at the end of every rule, whether or not the schema's description ends with one.
- Works for any schema config checks (actor, runtime, every runner's options), with nothing specific to one runner.

**Non-Goals:**

- No listing of what each alternative needs when none is closest. The description is kept there. A list of thirteen
  step kinds would be longer than it's useful, and the issue offers it only as an alternative to naming the closest.
- The refused value is never named, in this or any config error (spec: config, "A refused config value is repeated
  nowhere"). The bad value's place and what's valid there are named instead, which meets the malformed-input rule's
  "unless secret": a config value may always be a secret.
- No change to the scripted runner's schema or to any description.
- A refusal still shows its first problem and how many more there are. For the issue's step that's `runner` (it must
  be a group) with "(1 more)", and `tools` once `runner` is fixed. Showing every problem would change every config
  refusal, and the owner decided on 2026-11-19 to keep the format.

## Decisions

**D1. A branch is set aside when the object plainly isn't that branch.** A branch is set aside when one of its errors,
at the object's own path, is `additionalProperties` (the object holds a key the branch doesn't define) or `type` (the
branch takes something else), or when one of its errors, at a field directly under the object, is `const` (a
discriminator such as an event's `type` differs). Every other failure (a missing field, a field of the wrong type, a
value outside a list) is something to fix in that branch, so the branch stays. `enum` isn't a discriminator: a field
like `onCancel` with a value outside its list is a fix, not a sign of another branch. The alternatives considered were
`jsonschema.best_match`, which picks one error and drops `tools`, and "fewest errors", which ranks a branch that takes
any object with few fields above the one whose key the object holds.

**D2. Only for objects, and only with exactly one branch left.** When the value isn't an object, or no branch or
several are left, the error is the alternatives' description as today. Objects are where alternatives are told apart
by their keys. For a scalar, such as Ollama's `think` (a boolean, or `low`, `medium` or `high`), setting the boolean
branch aside for a string would leave "it must be one of low, medium, high", dropping `true` and `false`; the
description says both. Several branches left means the object could be fixed towards more than one, and naming one
would guess.

**D3. The closest branch's errors go back through the same wording.** The kept branch's errors are expanded in place
of the `oneOf` error and handled by the same loop as top-level errors, so a `required` field is named at its own path
with its own fix, a key the person put inside a value under a map is still never shown (`_in_a_map`), and a nested
`oneOf` (the step's event) is expanded the same way. The expanded list is sorted by path like the rest, so the first
problem shown stays stable.

**D4. A description's own full stop is dropped in `_rule`.** `_rule` strips one trailing full stop from a description
before quoting it, so `_refuse`'s full stop is the only one, and the `(n more)` count still comes before it.

## Risks / Trade-offs

- [A branch is set aside wrongly, so the closest one is a different kind than the person meant] → the set-aside tests
  are the ones a value can't pass by fixing a field, and a wrong pick still names real failures at real paths, never
  less than the description did. Tests cover the issue's input, the event's `type` discriminator, and an object whose
  key no branch defines (description kept).
- [A schema with `oneOf` branches of plain `required` lists, like the scripted options' `script`/`scriptPath`, keeps
  its description] → both branches fail only `required`, so neither is set aside and the description is given, as
  today; the existing test for missing options holds.
