# plugin-sdk Specification

## Purpose
Capability: `cap:plugins`, `cap:protocol`

The plugin SDK: one small, framework-free package with the public API that plugins build against, starting with the
runner contract's types and running a model's tool calls. Core takes the contract's types from it too, so they have
one definition, and plugins depend on it instead of on core.

## Requirements

### Requirement: The SDK imports nothing of troupe's
The `troupe-plugin-sdk` package SHALL NOT import `troupe` or any other workspace package. A check SHALL fail the
build when it does, naming the import.

#### Scenario: The SDK imports core
- **WHEN** a module under `packages/troupe-plugin-sdk/` imports `troupe.core`
- **THEN** the import contract check fails, naming the importing module and `troupe.core`

### Requirement: The SDK depends only on the standard library
The SDK's package SHALL declare no dependencies, so a plugin that uses it inherits nothing else. Its API SHALL be
plain functions and immutable values, and SHALL NOT require a plugin to run in a particular way.

#### Scenario: The SDK's declared dependencies
- **WHEN** the repository's check reads `packages/troupe-plugin-sdk/pyproject.toml`
- **THEN** its dependencies are empty, or the check fails naming the dependency and the file

### Requirement: The runner contract's types have one definition
The runner contract's message types, its protocol version and its JSON-RPC error codes SHALL be defined in the SDK
alone. Core and every runner plugin SHALL use the SDK's, and SHALL NOT define their own copy.

#### Scenario: Core and the scripted runner read the same event type
- **WHEN** core's runner host parses a `tool_call` event that the scripted runner sent
- **THEN** both use the SDK's type for it, and neither package defines a `tool_call` type of its own

#### Scenario: A runner plugin's protocol version
- **WHEN** the scripted runner or the Claude Code runner answers `initialize`
- **THEN** the protocol versions it supports are the SDK's

### Requirement: The SDK's types are checked against the contract's schemas
Every runner message type in the SDK SHALL be checked by tests against its schema in `protocol/schemas/runner/`:
what a type writes SHALL validate, and what the schema refuses SHALL fail to parse, naming where.

#### Scenario: A type that drifts from its schema
- **WHEN** a field is added to `run-event.schema.json`'s `tool_result` and not to the SDK's type
- **THEN** the SDK's tests fail, naming the type and the field

#### Scenario: An unknown field
- **WHEN** the SDK parses a `tool_call` event that has a field the schema doesn't define
- **THEN** it raises a protocol error naming the event and the field

### Requirement: Plugins depend on the SDK, never on core
No package under `plugins/` SHALL import `troupe` or another workspace package except the SDK. The import check
SHALL cover every package under `plugins/`, and SHALL fail when one is missing from it.

#### Scenario: A plugin imports core
- **WHEN** code under `plugins/runner-scripted/` imports `troupe.core.runners`
- **THEN** the import contract check fails

#### Scenario: A plugin imports the SDK
- **WHEN** code under `plugins/runner-scripted/` imports `troupe_plugin_sdk`
- **THEN** the import contract check passes

#### Scenario: A new plugin left out of the check
- **WHEN** a package is added under `plugins/` and not named in the import contract
- **THEN** the repository's check fails, naming the plugin and the contract to add it to

### Requirement: The SDK releases at its own version
The SDK SHALL be its own release component, `troupe-plugin-sdk`, with its own changelog and
`troupe-plugin-sdk-v<version>` tag. Core and the plugins SHALL depend on it bare; `troupe-run` SHALL pin it, as it
pins every package, so a tag install resolves it from its tag.

#### Scenario: Only the SDK changed
- **WHEN** the only releasable commit since the last release is a `fix:` that changes `packages/troupe-plugin-sdk/`
- **THEN** the release pull request releases `troupe-plugin-sdk` alone, at its next patch version

#### Scenario: Installed from a bundle tag
- **WHEN** a `troupe-run` tag that pins `troupe-plugin-sdk-v0.1.0` is installed with `--no-sources`
- **THEN** the SDK is installed from the `troupe-plugin-sdk-v0.1.0` tree, for core and for every plugin, and never
  looked up on a package index

### Requirement: The SDK reads the declaration from run start
The SDK SHALL turn a `run/start`'s `effects`, `workspace` and `scratch` into one immutable declaration a runner can
apply, refusing a malformed pattern with a protocol error naming the effect and the pattern. Its patterns SHALL be
the ones the contract's schema accepts, no more and no fewer.

#### Scenario: A run start with write declared
- **WHEN** a runner reads a `run/start` whose `effects.write` is `["out/**"]`
- **THEN** the declaration allows writing `out/a.txt`, not `src/a.txt`, and allows no delete or move

#### Scenario: A malformed pattern in run start
- **WHEN** a runner reads a `run/start` whose `effects.delete` holds `../x`
- **THEN** reading it raises a protocol error naming `delete` and `../x`

### Requirement: Runners plug in their own way of applying the declaration
The SDK SHALL define a framework-free interface for translating a declaration into a runner's own form, and SHALL
give every implementation the same normalised view of it: each effect's patterns as absolute patterns with `/`
between their parts, rooted at the workspace, and the scratch directory, in the same form on every platform. Each
implementation SHALL say which `init` value it reports. The SDK's own tools SHALL be the `checked` implementation.

#### Scenario: A pattern on Windows
- **WHEN** the workspace is `C:\work\theatre` and `write` declares `out/**`
- **THEN** the normalised pattern is `/c/work/theatre/out/**`

#### Scenario: Two runners, one declaration
- **WHEN** the SDK's tools and a runner's own translation are given the same declaration
- **THEN** both see the same normalised patterns and the same scratch directory

### Requirement: The SDK estimates a cost from usage and a price
The SDK SHALL give runners one estimator that takes a run's usage and `run/start`'s price and returns the estimate in
US dollars, rounded to ten decimal places, or nothing when the contract says an estimate is absent (spec:
runner-protocol). Runners that estimate SHALL use it.

#### Scenario: Every counter priced
- **WHEN** the estimator is given 1,000,000 input, 200,000 cache-read, 100,000 cache-write and 500,000 output tokens,
  and rates of 2, 0.5, 2.5 and 8 dollars per million
- **THEN** it returns 6.35

#### Scenario: No usage
- **WHEN** the estimator is given no usage and a price
- **THEN** it returns nothing

#### Scenario: Agrees with the contract on every input
- **WHEN** the estimator is given generated usages and prices, counters and rates each present or absent
- **THEN** it returns nothing exactly when the contract says an estimate is absent, and otherwise a number of zero or
  more equal to the sum of each counter times its rate over a million

### Requirement: The SDK's result type carries the reason
The SDK's result event SHALL carry the reason, typed as the contract's closed list. Building or parsing a result SHALL
refuse an `error` result without a reason and an `ok` result with one, naming the event and `reason`.

#### Scenario: A runner builds an error result without a reason
- **WHEN** a runner builds the SDK's result event with status `error` and no reason
- **THEN** the SDK raises an error naming the result event and `reason`, and nothing is sent

#### Scenario: The host parses an error result without a reason
- **WHEN** the host parses a `result` event with status `error` and no reason
- **THEN** the SDK raises a protocol error naming the result event and `reason`

#### Scenario: An ok result with a reason
- **WHEN** a runner builds the SDK's result event with status `ok` and reason `budget`
- **THEN** the SDK raises an error naming the result event and `reason`

#### Scenario: The reason list matches the schema
- **WHEN** a reason is added to `run-event.schema.json`'s list and not to the SDK's type
- **THEN** the SDK's tests fail, naming the result type and the reason
