# config-files: delta

## MODIFIED Requirements

### Requirement: Each actor is projected to its own files
Each actor in config SHALL be written to `.troupe/actors/<name>.yaml`, holding every field of the actor schema that
config sets, other than the character, in the schema's order, and its character, when it has one, to
`.troupe/actors/<name>.md`, whose whole content is the character's text. An actor with no character SHALL have no
`.md` file.

#### Scenario: An actor with a character
- **WHEN** config has the actor `tester` with a runner, an effect check and a character
- **THEN** `.troupe/actors/tester.yaml` holds the runner and the effect check
- **AND** `.troupe/actors/tester.md` holds the character's text, byte for byte

#### Scenario: An actor's effects, workspace, runtime and model
- **WHEN** a person runs `troupe config set actors.tester.runner=scripted 'actors.tester.expect=[]'
  'actors.tester.effects.write=["out/**"]' actors.tester.workspace=theatre actors.tester.runtime=ollama
  actors.tester.model=llama3.2`
- **THEN** `.troupe/actors/tester.yaml` holds `runner`, `expect`, `effects`, `workspace`, `runtime` and `model`, in
  the actor schema's order

#### Scenario: Every field config can set
- **WHEN** config sets every field the actor schema defines
- **THEN** the actor's file holds each of them, so a field added to the schema later can't be left out

#### Scenario: The file validates against its schema
- **WHEN** a written actor file is validated against the actor schema troupe carries
- **THEN** it is valid

#### Scenario: A removed actor
- **WHEN** `tester` is removed from config
- **THEN** its `.yaml` and `.md` files are removed
