# Spec Delta

## ADDED Requirements

### Requirement: The Anthropic audition can edit files on a small budget
The Anthropic example actor SHALL have `runner: anthropic`, `runtime: anthropic`, a `model` naming Claude's cheapest
current model that calls tools over the Messages API, named in one place in core, options with `maxTurns` of 10 and
`maxTotalTokens` of 100000, `effects` with `write: ["**"]`, an empty `expect`, and the same short character as the
Claude Code audition. It SHALL leave `workspace` unset.

#### Scenario: The Anthropic actor's file
- **WHEN** a person runs `troupe init --audition --runner anthropic`
- **THEN** config's `actors.lead` holds runner `anthropic`, runtime `anthropic`, the model, options with `maxTurns` 10
  and `maxTotalTokens` 100000, `effects.write: ["**"]` and `expect: []`, and no `workspace`
- **AND** `.troupe/actors/lead.md` holds the character

#### Scenario: What init prints for it
- **WHEN** a person runs `troupe init --audition --runner anthropic`
- **THEN** the perform step's note names the `troupe-run[anthropic]` extra, says the `anthropic` runtime's key must be
  set in `ANTHROPIC_API_KEY`, and says a run costs money, within the actor's token budget
