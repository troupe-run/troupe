# openai-runner: delta

## ADDED Requirements

### Requirement: The runtime's endpoint has a path
The runner SHALL refuse `run/start` with `openai.no-runtime`, where `runtime.endpoint`, when the runtime's endpoint
has no path, before any request is sent: an OpenAI-style service serves its API under one, such as `/v1`. The error
SHALL say so and name an endpoint that would fit, and SHALL NOT repeat an endpoint that holds user info.

#### Scenario: Ollama's own address
- **WHEN** a `run/start`'s runtime endpoint is `http://127.0.0.1:11434`
- **THEN** `run/start` is refused with `openai.no-runtime`, where `runtime.endpoint`, saying the endpoint needs a path
  such as `/v1`, and no request is sent

#### Scenario: A trailing slash alone
- **WHEN** a `run/start`'s runtime endpoint is `https://example.com/`
- **THEN** it is refused the same way

#### Scenario: An endpoint with a path
- **WHEN** a `run/start`'s runtime endpoint is `http://127.0.0.1:11434/v1`
- **THEN** the run's requests go to `http://127.0.0.1:11434/v1/responses`

## MODIFIED Requirements

### Requirement: The credential is read from TROUPE_RUNTIME_CREDENTIAL
The runner SHALL read the run's credential only from `TROUPE_RUNTIME_CREDENTIAL`, and only when `run/start`'s
`runtime.credential` is `true`. When the two disagree, it SHALL refuse `run/start` with `openai.credential-mismatch`,
saying which way without the value, and send nothing. A credential holding any character other than visible ASCII
SHALL be refused with `openai.malformed-credential`, naming the variable and never the value.

#### Scenario: A credential run start promises and the environment lacks
- **WHEN** `runtime.credential` is `true` and `TROUPE_RUNTIME_CREDENTIAL` isn't set
- **THEN** `run/start` is refused with `openai.credential-mismatch`, and no request is sent

#### Scenario: A credential run start doesn't mention
- **WHEN** `runtime.credential` is `false` and `TROUPE_RUNTIME_CREDENTIAL` holds a value
- **THEN** `run/start` is refused with `openai.credential-mismatch`, and the error holds no part of the value

#### Scenario: A key read with its line ending
- **WHEN** `TROUPE_RUNTIME_CREDENTIAL` holds a key followed by `\r\n`
- **THEN** `run/start` is refused with `openai.malformed-credential`, the error holds no part of the key, and no
  request is sent

#### Scenario: A key holding a character outside ASCII
- **WHEN** `TROUPE_RUNTIME_CREDENTIAL` holds `sk-test-€abcdefgh`
- **THEN** `run/start` is refused with `openai.malformed-credential`, the error holds no part of the key, and no
  request is sent
