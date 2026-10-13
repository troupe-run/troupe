# Spec Delta

## ADDED Requirements

### Requirement: Absent fields are left out, never sent as null
A field with nothing to say SHALL be left out, and each optional field's description SHALL say what its absence
means. Where a value with its own meaning exists, it SHALL be used instead of absence. A sentinel that loses meaning,
such as `""` or `-1`, SHALL NOT stand in for absence.

#### Scenario: An optional field with nothing to say
- **WHEN** troupe writes a payload in which an optional field has no value
- **THEN** the field is left out of the payload, and is never present with the value `null`

#### Scenario: An optional property with no description
- **WHEN** a schema declares a property that isn't required there and has no `description`, and no node that
  always applies to the same value (an enclosing node, or what it reaches by `$ref` or `allOf`) requires or
  describes it
- **THEN** the build fails, naming the file and the property

#### Scenario: A field only a branch declares
- **WHEN** a `oneOf` or `then` branch declares a property that nothing enclosing it declares, and gives it no
  `description`
- **THEN** the build fails, naming the branch's property, even when a sibling branch describes the same name

### Requirement: Null is accepted only where it is marked
A schema SHALL accept `null`, by `type`, `const` or `enum`, only on a node that carries the null marker. The marker
SHALL name its kind: `clear` (in an update, "clear this", which absence can't say) or `external` (a format troupe
doesn't own requires it). It SHALL also say what the `null` means. A marker on a node that accepts no `null` is an
error.

#### Scenario: An unmarked null
- **WHEN** a schema accepts `null` by `"type": "null"`, a `type` list containing `"null"`, `"const": null`, or an
  `enum` containing `null`, on a node without the marker
- **THEN** the build fails, naming the file and the location

#### Scenario: A marked null
- **WHEN** a node accepts `null` and carries a well-formed marker
- **THEN** the strictness check accepts it

#### Scenario: A malformed marker
- **WHEN** a marker's kind is neither `clear` nor `external`, its meaning is empty, or it has fields other than
  those two
- **THEN** the build fails, naming the location

#### Scenario: A stray marker
- **WHEN** a node carries the marker but accepts no `null`
- **THEN** the build fails, naming the location

#### Scenario: Null in a condition
- **WHEN** `null` appears only inside `if` or `not`, which never widen what is accepted
- **THEN** the strictness check doesn't report it

### Requirement: The JSON-RPC error id is the one marked null
The only `null` in the schemas troupe ships SHALL be the `id` of a runner error response, marked `external`, because
JSON-RPC 2.0 requires `"id": null` when the failed request couldn't be read.

#### Scenario: Every shipped schema
- **WHEN** the strictness check runs over every schema in `protocol/` and in each plugin
- **THEN** the only node accepting `null` is `runner/error-response.schema.json#/properties/id`'s null branch, and it
  carries an `external` marker

## MODIFIED Requirements

### Requirement: The strictness check proves itself
The strictness check SHALL be tested against schemas that break each rule, and SHALL reject every one of them, so
it can't pass by checking nothing.

#### Scenario: A known-bad schema
- **WHEN** the check is given a schema with an open object, an untyped value, `true`, `{}`, an untyped map or an
  array with no items
- **THEN** it reports that schema, at the location that breaks the rule

#### Scenario: A known-bad null
- **WHEN** the check is given a schema that accepts an unmarked `null` in each of its four forms, a malformed
  marker, a stray marker, or an optional property with no description
- **THEN** it reports that schema, at the location that breaks the rule
