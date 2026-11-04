# Spec Delta

## MODIFIED Requirements

### Requirement: Init's audition runner is named with --runner
`troupe init --audition --runner <runner>` SHALL define the example actor for that runner. Claude Code SHALL be the
runner when `--runner` is absent. A runner troupe doesn't know SHALL be refused with `runner.unknown`, naming the
runners troupe has, before anything is made. `--runner` without `--audition` SHALL be refused as a usage error.

#### Scenario: The scripted runner
- **WHEN** a person runs `troupe init --audition --runner scripted`
- **THEN** `.troupe/actors/lead.yaml` names the runner `scripted`

#### Scenario: The Ollama runner
- **WHEN** a person runs `troupe init --audition --runner ollama`
- **THEN** `.troupe/actors/lead.yaml` names the runner `ollama`

#### Scenario: A runner troupe doesn't know
- **WHEN** a person runs `troupe init --audition --runner gemini`
- **THEN** it fails with `runner.unknown`, naming `gemini`, `claude-code`, `ollama` and `scripted`
- **AND** no `.troupe/` is made

#### Scenario: A runner without an audition
- **WHEN** a person runs `troupe init --runner scripted`
- **THEN** it exits with the usage-error code, with `usage.missing-argument` naming `troupe init` and `--audition`
- **AND** no `.troupe/` is made
