# Spec Delta

## ADDED Requirements

### Requirement: Each runtime in config is projected to its own file
Each runtime in the theatre's config SHALL be written to `.troupe/runtimes/<name>.yaml`, holding only the fields
config sets, and naming its schema as every config file does, by the protocol's major version
(`config/runtime.schema.json`). A built-in runtime config doesn't set SHALL have no file.

#### Scenario: An override of a built-in
- **WHEN** config sets only `runtimes.openai.model=gpt-test`
- **THEN** `.troupe/runtimes/openai.yaml` holds its two schema lines and `model: gpt-test`, and nothing else

#### Scenario: No runtimes in config
- **WHEN** config has no `runtimes`
- **THEN** there's no `.troupe/runtimes/` directory

#### Scenario: A removed runtime
- **WHEN** `runtimes.myhost` is removed from config
- **THEN** `.troupe/runtimes/myhost.yaml` is removed

#### Scenario: The file validates against its schema
- **WHEN** a written runtime file is validated against the runtime schema troupe carries
- **THEN** it is valid

### Requirement: Runtime files are a known kind
`.troupe/runtimes/<name>.yaml` SHALL be a kind in the registry of file kinds. Any other file in `.troupe/runtimes/`
SHALL be refused when flushing with `config.unknown-file`, as in any config directory.

#### Scenario: A stray file
- **WHEN** `.troupe/runtimes/notes.txt` exists and a person runs `troupe flush`
- **THEN** it is refused with `config.unknown-file`, naming the file
