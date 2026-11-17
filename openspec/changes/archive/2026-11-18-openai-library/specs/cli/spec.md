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
- **WHEN** a person runs `troupe init --audition --runner ollama` with its extra installed
- **THEN** `.troupe/actors/lead.yaml` names the runner `ollama`

#### Scenario: The OpenAI runner
- **WHEN** a person runs `troupe init --audition --runner openai` with its extra installed
- **THEN** `.troupe/actors/lead.yaml` names the runner `openai`, and config's `actors.lead.runtime` is `openai`

#### Scenario: The Anthropic runner
- **WHEN** a person runs `troupe init --audition --runner anthropic` with its extra installed
- **THEN** `.troupe/actors/lead.yaml` names the runner `anthropic`, and config's `actors.lead.runtime` is `anthropic`

#### Scenario: A runner troupe doesn't know
- **WHEN** a person runs `troupe init --audition --runner gemini`
- **THEN** it fails with `runner.unknown`, naming `gemini`, `anthropic`, `claude-code`, `mistralrs`, `ollama`,
  `openai` and `scripted`
- **AND** no `.troupe/` is made

#### Scenario: The LM Studio runner
- **WHEN** a person runs `troupe init --audition --runner lm-studio`
- **THEN** it fails with `runner.unknown`, naming `lm-studio` and the runners troupe has
- **AND** no `.troupe/` is made

#### Scenario: A runner that isn't installed
- **WHEN** a person runs `troupe init --audition --runner example`, whose extra is `example`, without it installed
- **THEN** it fails with `runner.not-installed`, naming `example` and `troupe-run[example]`
- **AND** no `.troupe/` is made, and `--rehearse` refuses the same way

#### Scenario: The Anthropic runner when it isn't installed
- **WHEN** a person runs `troupe init --audition --runner anthropic` without its extra installed
- **THEN** it fails with `runner.not-installed`, naming `anthropic` and `troupe-run[anthropic]`
- **AND** no `.troupe/` is made

#### Scenario: The Ollama runner when it isn't installed
- **WHEN** a person runs `troupe init --audition --runner ollama` without its extra installed
- **THEN** it fails with `runner.not-installed`, naming `ollama` and `troupe-run[ollama]`
- **AND** no `.troupe/` is made

#### Scenario: The OpenAI runner when it isn't installed
- **WHEN** a person runs `troupe init --audition --runner openai` without its extra installed
- **THEN** it fails with `runner.not-installed`, naming `openai` and `troupe-run[openai]`
- **AND** no `.troupe/` is made

#### Scenario: A runner without an audition
- **WHEN** a person runs `troupe init --runner scripted`
- **THEN** it exits with the usage-error code, with `usage.missing-argument` naming `troupe init` and `--audition`
- **AND** no `.troupe/` is made
