# Spec Delta

## Purpose

The rules every schema troupe publishes follows, in `protocol/` and in each plugin: JSON Schema that is strict,
so every value troupe reads or writes has a known shape that tools, editors and other languages can check.

## ADDED Requirements

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
