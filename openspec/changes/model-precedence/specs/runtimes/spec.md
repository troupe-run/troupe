## ADDED Requirements

### Requirement: The run's model comes from the actor, the environment, then the runtime
A run's model SHALL be the actor's `model` when it sets one, else the runtime's `TROUPE_RUNTIME_<NAME>_MODEL` when
set, else the runtime's `model` in config, with its source `actor`, `env` or `theatre`. A run whose runtime resolves
no model SHALL be refused with `runtime.no-model` before anything is recorded.

#### Scenario: The actor's model wins over the environment
- **WHEN** config sets `runtimes.openai.model=gpt-a` and `actors.tester.model=gpt-b`, and
  `TROUPE_RUNTIME_OPENAI_MODEL` is `gpt-c`
- **THEN** a run of `tester` uses `gpt-b`, with source `actor`

#### Scenario: The environment wins over the runtime's model
- **WHEN** config sets `runtimes.openai.model=gpt-a`, `tester` sets no model, and `TROUPE_RUNTIME_OPENAI_MODEL` is
  `gpt-c`
- **THEN** a run of `tester` uses `gpt-c`, with source `env`

#### Scenario: The runtime's model
- **WHEN** config sets `runtimes.openai.model=gpt-a`, `tester` sets no model, and no variable sets one
- **THEN** a run of `tester` uses `gpt-a`, with source `theatre`

#### Scenario: No model anywhere
- **WHEN** an actor on `openai` sets no model, config sets none, and no variable sets one
- **THEN** perform fails with `runtime.no-model`, naming `actors.tester.model`, `runtimes.openai.model` and
  `TROUPE_RUNTIME_OPENAI_MODEL`, and nothing is recorded

## MODIFIED Requirements

### Requirement: A run's price is the price of its model
A run's price SHALL be the price its runtime's `prices` holds for the run's model, matched exactly, with source
`theatre`. A run whose model has no price SHALL have none. No environment variable SHALL set a price.

#### Scenario: The actor's model is priced
- **WHEN** config prices `gpt-a` and `gpt-b` on `openai`, and a run of `tester` uses `gpt-b` from the actor
- **THEN** the run's price is `gpt-b`'s

#### Scenario: The model from the environment has no price
- **WHEN** config prices only `gpt-b`, `tester` sets no model, and `TROUPE_RUNTIME_OPENAI_MODEL` makes a run of
  `tester` use `gpt-c`
- **THEN** the run has no price

#### Scenario: A near match
- **WHEN** config prices `gpt-b` and a run uses `gpt-b-2026-01-01`
- **THEN** the run has no price

## REMOVED Requirements

### Requirement: The run's model comes from the environment, the actor, then the runtime
**Reason**: The environment beat the actor's own model, the reverse of the precedence every other setting follows
(troupe-run/troupe#451). Replaced by "The run's model comes from the actor, the environment, then the runtime".
**Migration**: To change the model of an actor that sets its own, set or unset its `model`
(`troupe config set actors.<name>.model=<model>`). `TROUPE_RUNTIME_<NAME>_MODEL` still sets the model for every actor
on the runtime that sets none.
