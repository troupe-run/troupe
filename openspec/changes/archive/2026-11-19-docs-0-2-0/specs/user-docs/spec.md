## ADDED Requirements

### Requirement: The first run has a path for every runner
The first-run walkthrough SHALL give, for every runner troupe has, a section that sets up an actor on it with
`troupe init --audition` (naming the runner with `--runner` unless it's the default) and runs `troupe perform lead`, saying what to install
and which credential or model it needs. Each command a section gives SHALL run as written in the docs check, against
a stand-in for the runner's service or engine. The docs check SHALL fail when a runner troupe has has no section.

#### Scenario: The Anthropic path runs as written
- **WHEN** the docs check runs each command of the `anthropic` runner's section, in order, in a new git repository,
  with a stand-in Messages API service in place of Claude's API
- **THEN** its `troupe perform lead` prints `run <id> succeeded` and exits 0

#### Scenario: The mistral.rs path runs as written
- **WHEN** the docs check runs each command of the `mistralrs` runner's section, in order, in a new git repository,
  with the engine stand-in in place of mistral.rs and its model
- **THEN** its `troupe perform lead` prints `run <id> succeeded` and exits 0

#### Scenario: A runner with no path
- **WHEN** troupe gains a runner and the first-run walkthrough has no section for it
- **THEN** the docs check fails, naming the runner and the page

### Requirement: No page offers a runner troupe doesn't have
Every runner a page under `docs/` names in a command or config line, as `--runner <name>` or `runner=<name>`, SHALL be
one troupe has. The docs check SHALL fail otherwise, naming the page, the line and the runners troupe has.

#### Scenario: A removed runner
- **WHEN** a page still says `troupe init --audition --runner lm-studio`
- **THEN** the docs check fails, naming the page, the line, `lm-studio` and the runners troupe has

#### Scenario: An engine reached through another runner
- **WHEN** a page defines a runtime for LM Studio and points an actor on the `anthropic` runner at it
- **THEN** the docs check passes
