## MODIFIED Requirements

### Requirement: A change to an actor on a runner that isn't installed is refused
A change that leaves an actor on a runner that troupe knows but isn't installed, and sets or unsets anything under that
actor, SHALL be refused with `runner.not-installed`, recording nothing, since its options can't be checked. The error
SHALL name the actor's path, the runner and its extra. Removing the actor whole, or moving it to an installed runner,
SHALL NOT be refused for this.

#### Scenario: Defining an actor on an uninstalled runner
- **WHEN** a person runs `troupe config set actors.lead.runner=example` and the `example` runner, whose extra is
  `example`, isn't installed
- **THEN** it is refused with `runner.not-installed`, naming `actors.lead.runner`, `example` and
  `troupe-run[example]`
- **AND** nothing is recorded

#### Scenario: Changing an existing actor's character
- **WHEN** `lead` is on the `example` runner, which isn't installed, and a person sets `actors.lead.character`
- **THEN** it is refused with `runner.not-installed`, and nothing is recorded

#### Scenario: Removing the actor
- **WHEN** `lead` is on the `example` runner, which isn't installed, and a person runs `troupe config unset
  actors.lead`
- **THEN** the change is recorded

#### Scenario: Moving the actor to an installed runner
- **WHEN** `lead` is on the `example` runner, which isn't installed, and a person sets `actors.lead.runner=scripted`
  and unsets `actors.lead.options`
- **THEN** the change is checked against the scripted runner's options schema, and recorded when it passes

### Requirement: Another actor's uninstalled runner doesn't block config
When config is checked whole, for a change to something else or a merge, an actor whose runner troupe knows but isn't
installed SHALL be checked against the actor schema and the effects rules, and its options SHALL be left unchecked
rather than refused. Its options are checked when it is next changed or performed where its runner is installed.

#### Scenario: Changing another actor
- **WHEN** `lead` is on the `example` runner, which isn't installed, and a person sets `actors.tester.runner=scripted`
- **THEN** the change is recorded

#### Scenario: A merge on a machine without the runner
- **WHEN** two branches' config streams are merged where `lead`'s `example` runner isn't installed, and one branch
  changed `lead`'s options
- **THEN** the merge isn't in conflict for `lead`'s options, and performing `lead` there is refused with
  `runner.not-installed`

#### Scenario: The actor's effects are still checked
- **WHEN** `lead` is on the `example` runner, which isn't installed, one branch expects `docs/a.md` while `lead` may
  write `docs/**`, and another narrows its writes to `out/**`, and they are merged
- **THEN** the merge is in conflict, naming `lead` and that an `expect` item, by its position, isn't covered by any
  effect

## REMOVED Requirements

### Requirement: The LM Studio audition can edit files with a small local model
**Reason**: The LM Studio runner is removed (#412, #413), and its audition with it.
**Migration**: None needed: it was never released. `troupe init --audition --runner lm-studio` is refused with
`runner.unknown`.
