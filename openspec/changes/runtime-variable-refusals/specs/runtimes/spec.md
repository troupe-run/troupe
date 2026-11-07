## MODIFIED Requirements

### Requirement: A malformed runtime variable is an error
A runtime variable that is set but isn't a value its field accepts SHALL fail the command that resolves the runtime
with `runtime.invalid-value`, naming the variable and what the field accepts, and never the value, in its problem, its
fix or its details. It SHALL NOT fall through.

#### Scenario: An endpoint that isn't a URL
- **WHEN** `TROUPE_RUNTIME_OLLAMA_ENDPOINT` is `localhost:11434` and a person performs an actor on `ollama`
- **THEN** perform fails with `runtime.invalid-value`, naming the variable and that it must be an `http` or `https`
  URL, the error holds no part of `localhost:11434`, and nothing is recorded

#### Scenario: A key where a variable's name should be
- **WHEN** `TROUPE_RUNTIME_OPENAI_CREDENTIAL_ENV` holds a key, `sk-test q7ZxW9pL`, rather than a variable's name, and
  a person runs `troupe config get --resolved runtimes.openai`
- **THEN** it fails with `runtime.invalid-value`, naming `TROUPE_RUNTIME_OPENAI_CREDENTIAL_ENV` and that it must be a
  variable's name, and nothing the client receives holds the key

#### Scenario: An endpoint carrying a password
- **WHEN** `TROUPE_RUNTIME_OLLAMA_ENDPOINT` is `https://user:hunter2-secret@example.com/v1`
- **THEN** resolving `ollama` fails with `runtime.invalid-value`, and the error holds neither the URL nor
  `hunter2-secret`

### Requirement: A run's credential is read from the named variable when the run starts
When a run's runtime has a credential, perform SHALL read its value from the variable `credential.env` names, in the
session's environment, when the run starts. An unset or empty variable SHALL refuse the run with
`runtime.credential-unset`, naming the runtime and the variable (as "A refusal never repeats a credential variable's
name taken from the environment" says), before anything is recorded.

#### Scenario: The key isn't set
- **WHEN** an actor on `openai` is performed and `OPENAI_API_KEY` isn't set
- **THEN** perform fails with `runtime.credential-unset`, naming `openai` and `OPENAI_API_KEY`, and nothing is
  recorded

### Requirement: A credential too short to mask is refused
A credential whose value is shorter than troupe's named minimum, 8 bytes by default, SHALL refuse the run with
`runtime.credential-too-short`, naming the runtime and the variable (as "A refusal never repeats a credential
variable's name taken from the environment" says) but not the value, before anything is recorded.

#### Scenario: A placeholder key
- **WHEN** a runtime's credential variable holds `ollama`
- **THEN** perform fails with `runtime.credential-too-short`, naming the variable and the minimum, and the error holds
  no part of the value

## ADDED Requirements

### Requirement: A credential holding whitespace or a control character is refused
A run's credential whose value holds whitespace or a control character SHALL refuse the run with
`runtime.credential-malformed`, naming the runtime and the variable (as "A refusal never repeats a credential
variable's name taken from the environment" says) but not the value, before anything is recorded and before any runner
is started.

#### Scenario: A key read with its line ending
- **WHEN** `OPENAI_API_KEY` holds `sk-test-q7ZxW9pL4vR2\r\n` and an actor on `openai` is performed
- **THEN** perform fails with `runtime.credential-malformed`, naming `openai` and `OPENAI_API_KEY`, the error holds no
  part of the value, no runner is started, and nothing is recorded

#### Scenario: A space inside the key
- **WHEN** a runtime's credential variable holds `sk-test q7ZxW9pL4vR2`
- **THEN** the run is refused with `runtime.credential-malformed`

#### Scenario: A well-formed key
- **WHEN** a runtime's credential variable holds `sk-test-q7ZxW9pL4vR2` and its endpoint is `https`
- **THEN** the run starts with that credential

### Requirement: A refusal never repeats a credential variable's name taken from the environment
When a run's credential variable is named by `TROUPE_RUNTIME_<NAME>_CREDENTIAL_ENV`, `runtime.credential-unset`,
`runtime.credential-malformed` and `runtime.credential-too-short` SHALL name that `TROUPE_RUNTIME_` variable instead of
the name it holds, and SHALL hold no part of that name. A name from the theatre's config or a built-in runtime SHALL be
named as it is.

#### Scenario: A key where the variable's name should be
- **WHEN** `TROUPE_RUNTIME_OPENAI_CREDENTIAL_ENV` is `a3f9c2e17b4d8e05f6a1`, no variable of that name is set, and an
  actor on `openai` is performed
- **THEN** perform fails with `runtime.credential-unset`, naming `openai` and `TROUPE_RUNTIME_OPENAI_CREDENTIAL_ENV`,
  the error holds no part of `a3f9c2e17b4d8e05f6a1`, and nothing is recorded

#### Scenario: A name from config
- **WHEN** config sets `runtimes.openai.credential.env=MY_KEY`, `MY_KEY` isn't set, and an actor on `openai` is
  performed
- **THEN** perform fails with `runtime.credential-unset`, naming `MY_KEY`
