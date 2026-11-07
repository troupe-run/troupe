# Spec Delta

## MODIFIED Requirements

### Requirement: troupe has built-in runtimes
troupe SHALL define the runtimes `openai` (endpoint `https://api.openai.com/v1`, credential from `OPENAI_API_KEY`),
`ollama` (endpoint `http://127.0.0.1:11434`, no credential) and `lm-studio` (endpoint `http://127.0.0.1:1234`, no
credential), as defaults in one named place. No built-in runtime SHALL name a model.

#### Scenario: A built-in needs no config
- **WHEN** config has no `runtimes` and an actor names the runtime `ollama`
- **THEN** the actor is valid, and the runtime's endpoint is `http://127.0.0.1:11434` with source `default`

#### Scenario: LM Studio's built-in is its server root
- **WHEN** config has no `runtimes` and a person runs `troupe config get --resolved runtimes.lm-studio`
- **THEN** it shows the endpoint `http://127.0.0.1:1234` from `default`, the base LM Studio's native API lives under
