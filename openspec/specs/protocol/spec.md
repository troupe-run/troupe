# protocol Specification

## Purpose

Capability: `cap:protocol`

The rules every schema troupe publishes follows, in `protocol/` and in each plugin: JSON Schema that is strict,
so every value troupe reads or writes has a known shape that tools, editors and other languages can check.

## Requirements

### Requirement: Every schema is JSON Schema draft 2020-12
Every schema in `protocol/`, and every schema a plugin publishes, SHALL be a valid JSON Schema draft 2020-12
document with an `$id` that matches its path, and every reference in it SHALL resolve.

#### Scenario: A schema that isn't valid JSON Schema
- **WHEN** a schema file under `protocol/` or a plugin's `schemas/` is not a valid draft 2020-12 schema
- **THEN** the build fails, naming the file

#### Scenario: A reference that doesn't resolve
- **WHEN** a schema refers to a definition that doesn't exist
- **THEN** the build fails, naming the file and the reference

### Requirement: Every object is closed
Every subschema that accepts a JSON object SHALL be closed: it SHALL set `additionalProperties: false`, or be
evaluated under an enclosing `unevaluatedProperties: false`. A map, where keys are data rather than field names,
SHALL type its keys with `propertyNames` and its values with a schema.

#### Scenario: An open object
- **WHEN** a schema declares `"type": "object"` with neither `additionalProperties: false` nor an enclosing
  `unevaluatedProperties: false`
- **THEN** the build fails, naming the file and the location in it

#### Scenario: Properties declared in a composed branch
- **WHEN** a branch of `oneOf`, `allOf` or `if`/`then` declares properties, and the object containing it sets
  `unevaluatedProperties: false`
- **THEN** the strictness check accepts it

#### Scenario: A map with untyped keys
- **WHEN** a schema accepts an object whose `additionalProperties` is a schema but has no `propertyNames`
- **THEN** the build fails, naming the location

### Requirement: Every value is typed
Every subschema SHALL constrain what it accepts, by `type`, `const`, `enum`, a reference, or a composition of
subschemas that do. The schemas `true` and `{}` SHALL NOT appear where a value is accepted, and every array SHALL
say what its items are.

#### Scenario: A field with no type
- **WHEN** a property's schema carries only a title or description
- **THEN** the build fails, naming the location

#### Scenario: Anything goes
- **WHEN** a schema accepts a value with `true` or `{}`
- **THEN** the build fails, naming the location

#### Scenario: An array with no items
- **WHEN** a schema declares `"type": "array"` without `items`
- **THEN** the build fails, naming the location

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

### Requirement: A place that varies is an extension point with a closed default
Where a value's shape is defined outside the schema, such as a runner's options, the schema SHALL mark it as an
extension point (`$dynamicRef` to a `$dynamicAnchor`) whose default is closed. The default SHALL accept only what
is safe without the outside schema, and the outside schema SHALL itself pass the strictness check.

#### Scenario: No outside schema given
- **WHEN** a runner's options are validated against the contract alone
- **THEN** only an empty object validates

#### Scenario: A runner's schema fills the extension point
- **WHEN** the contract is validated together with a runner's published options schema
- **THEN** options that runner's schema accepts validate, and options it refuses don't

### Requirement: Every error and notice code is catalogued with its details
The protocol SHALL list every error and notice code troupe can produce, each with a closed schema for its
`details`, or none allowed. A code that isn't listed SHALL NOT validate. troupe's own catalogue of codes SHALL
match the protocol's, both ways.

#### Scenario: An unlisted code
- **WHEN** an error whose code isn't in the protocol's catalogue is validated
- **THEN** it doesn't validate

#### Scenario: Details that don't match the code
- **WHEN** an error carries a detail its code's schema doesn't define
- **THEN** it doesn't validate

#### Scenario: Catalogues agree
- **WHEN** troupe declares an error or notice code the protocol doesn't list, or the protocol lists one troupe
  doesn't declare
- **THEN** the build fails, naming the code

### Requirement: Every error, notice and recorded event is checked as tests make it
In the test suite, every error and notice troupe constructs, and every event troupe records, SHALL be validated
against its schema at the moment it's made, so a test that produces a shape the schema doesn't allow fails.

#### Scenario: A raise site with an undeclared detail
- **WHEN** a test exercises code that raises an error with a detail its code's schema doesn't define
- **THEN** that test fails, naming the code and the detail

#### Scenario: A recorded payload that drifts
- **WHEN** a test records an event whose payload doesn't match its topic's state schema
- **THEN** that test fails, naming the topic

### Requirement: Detail keys are camelCase
Every key in an error's or notice's `details` SHALL be camelCase, like the rest of the protocol.

#### Scenario: A snake_case detail key
- **WHEN** a code's details schema defines a key containing an underscore
- **THEN** the build fails, naming the code and the key

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

### Requirement: troupe carries the schemas it was built with
The troupe package SHALL carry a copy of every schema in `protocol/schemas/`, and core SHALL read schemas only from
that copy and from installed plugins' published schemas. Core SHALL NOT fetch a schema over the network. The quality
check SHALL fail when the copy differs from `protocol/schemas/`.

#### Scenario: A schema changed without its copy
- **WHEN** a schema in `protocol/schemas/` changes and the package's copy isn't regenerated
- **THEN** `scripts/check.py` fails, naming the schema and the command that regenerates the copy

#### Scenario: An installed troupe
- **WHEN** troupe is installed from a built wheel, with no checkout of this repository
- **THEN** it finds every schema it needs, by `$id`, without a network connection

### Requirement: A plugin's published schemas are installed with it
Each plugin's published schemas SHALL be installed with the plugin, so troupe can read them without starting the
plugin, and without importing it.

#### Scenario: A runner's options schema
- **WHEN** troupe checks an actor's options for the scripted runner
- **THEN** it reads the options schema the installed scripted runner publishes, and the runner isn't started

### Requirement: troupe records the protocol version it carries
The troupe package SHALL record the protocol version of its copy of `protocol/schemas/`: the protocol release that
copy belongs to. Core SHALL read it from that record, wherever it reports or writes the protocol version, and from
nowhere else. A record that is missing or isn't a version SHALL be an error naming the file, never a default.

#### Scenario: An installed troupe
- **WHEN** troupe is installed from a built wheel, with no checkout of this repository
- **THEN** it reports the protocol version it was built with, without a network connection

#### Scenario: A malformed record
- **WHEN** the recorded protocol version is `"next"`
- **THEN** reading it fails, naming the file and that it must be a version such as `0.2.0`

#### Scenario: Before the protocol's first release
- **WHEN** the protocol has never been released
- **THEN** the recorded version is `0.0.0`
