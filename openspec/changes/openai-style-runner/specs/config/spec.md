## ADDED Requirements

### Requirement: The OpenAI audition can edit files on a small budget
The OpenAI example actor SHALL have `runner: openai`, `runtime: openai`, a `model` naming a small current OpenAI model
that calls tools over the Responses API, named in one place in core, options with `maxTurns` of 10 and
`maxTotalTokens` of 100000, `effects` with `write: ["**"]`, an empty `expect`, and the same short character as the
Claude Code audition. It SHALL leave `workspace` unset.

#### Scenario: The OpenAI actor's file
- **WHEN** a person runs `troupe init --audition --runner openai`
- **THEN** `.troupe/actors/lead.yaml` holds runner `openai`, runtime `openai`, the model, options with `maxTurns` 10
  and `maxTotalTokens` 100000, `effects.write: ["**"]` and `expect: []`, and no `workspace`
- **AND** `.troupe/actors/lead.md` holds the character

#### Scenario: What init prints for it
- **WHEN** a person runs `troupe init --audition --runner openai`
- **THEN** the perform step's note says the `openai` runtime's key must be set in `OPENAI_API_KEY`, and that a run
  costs money, within the actor's token budget
