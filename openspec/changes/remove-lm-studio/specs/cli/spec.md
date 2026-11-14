## MODIFIED Requirements

### Requirement: Init's audition runner is named with --runner
`troupe init --audition --runner <runner>` SHALL define the example actor for that runner. Claude Code SHALL be the
runner when `--runner` is absent. A runner troupe doesn't know SHALL be refused with `runner.unknown`, naming the
runners troupe has, before anything is made. A runner troupe knows but isn't installed SHALL be refused with
`runner.not-installed`, naming its extra, before anything is made. `--runner` without `--audition` SHALL be refused as
a usage error.

#### Scenario: The scripted runner
- **WHEN** a person runs `troupe init --audition --runner scripted`
- **THEN** `.troupe/actors/lead.yaml` names the runner `scripted`

#### Scenario: The Ollama runner
- **WHEN** a person runs `troupe init --audition --runner ollama`
- **THEN** `.troupe/actors/lead.yaml` names the runner `ollama`

#### Scenario: The OpenAI runner
- **WHEN** a person runs `troupe init --audition --runner openai`
- **THEN** `.troupe/actors/lead.yaml` names the runner `openai`, and config's `actors.lead.runtime` is `openai`

#### Scenario: A runner troupe doesn't know
- **WHEN** a person runs `troupe init --audition --runner gemini`
- **THEN** it fails with `runner.unknown`, naming `gemini`, `claude-code`, `ollama`, `openai` and `scripted`
- **AND** no `.troupe/` is made

#### Scenario: The LM Studio runner
- **WHEN** a person runs `troupe init --audition --runner lm-studio`
- **THEN** it fails with `runner.unknown`, naming `lm-studio` and the runners troupe has
- **AND** no `.troupe/` is made

#### Scenario: A runner that isn't installed
- **WHEN** a person runs `troupe init --audition --runner example`, whose extra is `example`, without it installed
- **THEN** it fails with `runner.not-installed`, naming `example` and `troupe-run[example]`
- **AND** no `.troupe/` is made, and `--rehearse` refuses the same way

#### Scenario: A runner without an audition
- **WHEN** a person runs `troupe init --runner scripted`
- **THEN** it exits with the usage-error code, with `usage.missing-argument` naming `troupe init` and `--audition`
- **AND** no `.troupe/` is made

### Requirement: An audition on a runner in an extra names the extra
After an audition whose runner is installed through an extra of `troupe-run`, the perform step's notes SHALL say that
the runner comes with `troupe-run[<extra>]`, so whoever runs the theatre elsewhere installs it. An audition on a runner
in the base install SHALL NOT mention an extra.

#### Scenario: A library-backed runner
- **WHEN** a person with `troupe-run[example]` installed runs `troupe init --audition --runner example`
- **THEN** the perform step's notes name `troupe-run[example]` and the install page

#### Scenario: A base runner
- **WHEN** a person runs `troupe init --audition --runner scripted`
- **THEN** no step's notes mention an extra
