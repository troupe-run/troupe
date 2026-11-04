# Spec Delta

## ADDED Requirements

### Requirement: The Ollama audition can edit files with a small local model
The Ollama example actor SHALL have `runner: ollama`, options holding only `model`, a small tool-capable model named
in one place in core, `effects` with `write: ["**"]`, an empty `expect`, and the same short character as the Claude
Code audition. It SHALL leave `endpoint` and `workspace` unset, so its runs use the local Ollama and work in a
worktree.

#### Scenario: The Ollama actor's file
- **WHEN** a person runs `troupe init --audition --runner ollama`
- **THEN** `.troupe/actors/lead.yaml` holds runner `ollama`, options with only `model`, `effects.write: ["**"]` and
  `expect: []`, and no `workspace`
- **AND** `.troupe/actors/lead.md` holds the character

#### Scenario: What init prints for it
- **WHEN** a person runs `troupe init --audition --runner ollama`
- **THEN** the perform step's note says Ollama must be running, and names `ollama pull` with the actor's model
