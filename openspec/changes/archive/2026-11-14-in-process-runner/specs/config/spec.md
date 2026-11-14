## ADDED Requirements

### Requirement: The mistralrs audition can edit files with a model on this machine
The mistralrs example actor SHALL have `runner: mistralrs`, `runtime: mistralrs`, no `model`, since its model is the
GGUF file the person points `TROUPE_RUNTIME_MISTRALRS_MODEL` at, options with `maxTurns` of 10, `effects` with
`write: ["**"]`, an empty `expect`, and the same short character as the Claude Code audition. It SHALL leave
`workspace` unset.

#### Scenario: The mistralrs actor's file
- **WHEN** a person runs `troupe init --audition --runner mistralrs`
- **THEN** config's `actors.lead` holds runner `mistralrs`, runtime `mistralrs`, options with `maxTurns` 10,
  `effects.write: ["**"]` and `expect: []`, and no `model` or `workspace`
- **AND** `.troupe/actors/lead.md` holds the character

#### Scenario: What init prints for it
- **WHEN** a person runs `troupe init --audition --runner mistralrs`
- **THEN** the perform step's note names the `troupe-run[mistralrs]` extra, says to set
  `TROUPE_RUNTIME_MISTRALRS_MODEL` to the absolute path of a GGUF model file that can call tools, that the model runs
  inside the runner on this machine, and that on macOS troupe is installed on a uv-managed Python
  (`uv tool install --managed-python`)
