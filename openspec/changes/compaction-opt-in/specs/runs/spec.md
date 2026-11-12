## ADDED Requirements

### Requirement: A run's onContextFull comes from the actor and policy
`perform` SHALL work out each run's `onContextFull` from the actor's `onContextFull` and the `compaction` policy:
under `actors`, the actor's value, `fail` when absent; under `all`, `compact` unless the actor says `fail`; under
`none`, `fail`. It SHALL send that value in `run/start`.

#### Scenario: An actor that opts in
- **WHEN** the policy is `actors` and an actor with `onContextFull` `compact` is performed
- **THEN** its `run/start` has `onContextFull` `compact`

#### Scenario: An actor that says nothing
- **WHEN** the policy is `actors` and an actor without `onContextFull` is performed
- **THEN** its `run/start` has `onContextFull` `fail`

#### Scenario: Policy turns it on
- **WHEN** the policy is `all` and an actor without `onContextFull` is performed
- **THEN** its `run/start` has `onContextFull` `compact`

#### Scenario: An actor that keeps failing under all
- **WHEN** the policy is `all` and an actor with `onContextFull` `fail` is performed
- **THEN** its `run/start` has `onContextFull` `fail`

### Requirement: Policy none refuses an actor that asks to compact
When the `compaction` policy is `none`, `perform` SHALL refuse an actor whose `onContextFull` is `compact` with
`policy.compaction-forbidden`, naming the actor, `TROUPE_POLICY_COMPACTION` and how to fix it, before the run's
start is recorded and before any worktree is made.

#### Scenario: A forbidden opt-in
- **WHEN** `TROUPE_POLICY_COMPACTION` is `none` and an actor with `onContextFull` `compact` is performed
- **THEN** `perform` fails with `policy.compaction-forbidden`, naming the actor and the variable
- **AND** no run is recorded and no runner is started

#### Scenario: An actor that didn't ask
- **WHEN** `TROUPE_POLICY_COMPACTION` is `none` and an actor without `onContextFull` is performed
- **THEN** the run starts, and its `run/start` has `onContextFull` `fail`

### Requirement: A run's start records whether it may compact and why
The run's start SHALL record its `onContextFull` and its source: `actor` when the actor sets `onContextFull`,
otherwise `policy` when the `compaction` policy is `all` or `none`, otherwise `default`.

#### Scenario: Decided by the actor
- **WHEN** the policy is `actors` and an actor with `onContextFull` `compact` is performed
- **THEN** the run's start records `onContextFull` `compact` with source `actor`

#### Scenario: Decided by policy
- **WHEN** the policy is `all` and an actor without `onContextFull` is performed
- **THEN** the run's start records `onContextFull` `compact` with source `policy`

#### Scenario: The default
- **WHEN** the policy is `actors` and an actor without `onContextFull` is performed
- **THEN** the run's start records `onContextFull` `fail` with source `default`
