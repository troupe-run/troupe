# Spec Delta

## ADDED Requirements

### Requirement: The LM Studio audition can edit files with a small local model
The LM Studio example actor SHALL have `runner: lm-studio`, `runtime: lm-studio`, a `model` naming a small
tool-capable model, named in one place in core, options with `maxTurns` of 10 and `maxTotalTokens` of 100000, `effects` with `write: ["**"]`, an
empty `expect`, and the same short character as the Claude Code audition. It SHALL leave `workspace` unset.

#### Scenario: The LM Studio actor's file
- **WHEN** a person runs `troupe init --audition --runner lm-studio`
- **THEN** config's `actors.lead` holds runner `lm-studio`, runtime `lm-studio`, the model, options with
  `maxTurns` 10 and `maxTotalTokens` 100000, `effects.write: ["**"]` and `expect: []`, and no `workspace`
- **AND** `.troupe/actors/lead.md` holds the character

#### Scenario: What init prints for it
- **WHEN** a person runs `troupe init --audition --runner lm-studio`
- **THEN** the perform step's note names the `troupe-run[lm-studio]` extra, says LM Studio's server must be
  running with "Require Authentication" off, and names `lms get` with the actor's model
