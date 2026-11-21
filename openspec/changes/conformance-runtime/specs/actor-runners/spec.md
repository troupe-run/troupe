# Spec Delta

## ADDED Requirements

### Requirement: The conformance suite can be given a runtime through the environment
The env-driven conformance check SHALL take a runtime from `TROUPE_CONFORMANCE_RUNTIME`: a JSON object holding the
runtime's `name` and the fields a runtime has in config. It SHALL check the object as config checks a runtime, resolve
it as a run resolves one (built-in, then the object, then the session's `TROUPE_RUNTIME_<NAME>_*` variables), and give
it to the runner in every `run/start`.

#### Scenario: A built-in runtime by name
- **WHEN** `TROUPE_CONFORMANCE_RUNTIME` is `{"name": "openai", "model": "m"}` and `TROUPE_RUNTIME_OPENAI_ENDPOINT` names
  a stand-in
- **THEN** every `run/start` the suite sends carries the runtime `openai` with the stand-in's endpoint, the model `m`
  and the built-in's credential, read from `OPENAI_API_KEY`

#### Scenario: A runtime nothing gives a model
- **WHEN** neither `TROUPE_CONFORMANCE_RUNTIME`, troupe's built-in nor `TROUPE_RUNTIME_<NAME>_MODEL` sets a model
- **THEN** the check fails naming the object's `model` and `TROUPE_RUNTIME_<NAME>_MODEL`

#### Scenario: An outside runner's own runtime
- **WHEN** `TROUPE_CONFORMANCE_RUNTIME` names a runtime troupe doesn't build in, with an endpoint and a model
- **THEN** every `run/start` the suite sends carries that runtime, endpoint and model

#### Scenario: A runner that needs a runtime passes when given one
- **WHEN** the env-driven check runs against the OpenAI-style runner with a runtime naming a stand-in endpoint and a
  credential named by reference
- **THEN** every check passes

#### Scenario: No runtime is given
- **WHEN** `TROUPE_CONFORMANCE_RUNTIME` is unset or empty
- **THEN** the suite sends no runtime, as before

### Requirement: The conformance suite takes a credential only by reference
A runtime given to the env-driven check SHALL name its credential only by the variable that holds it. The suite SHALL
read the value from the session's environment, give it to the runner as `TROUPE_RUNTIME_CREDENTIAL` as a run does,
refuse it as a run refuses it, and never print it.

#### Scenario: The credential reaches the runner
- **WHEN** the runtime's `credential.env` names a variable that holds a key
- **THEN** the runner's environment holds the key as `TROUPE_RUNTIME_CREDENTIAL`, and no other variable of the
  session's

#### Scenario: The credential's variable isn't set
- **WHEN** the runtime's `credential.env` names a variable that isn't set
- **THEN** the check fails with `runtime.credential-unset`, naming the variable, before any runner starts

#### Scenario: A credential over plain HTTP to another host
- **WHEN** the runtime has a credential and an `http` endpoint whose host isn't loopback
- **THEN** the check fails with `runtime.insecure-endpoint` before any runner starts

#### Scenario: A key put where a name goes
- **WHEN** the runtime's `credential.env` holds something that isn't a variable's name
- **THEN** the check fails naming `TROUPE_CONFORMANCE_RUNTIME` and `credential.env`, and its message doesn't hold the
  value

### Requirement: The conformance suite masks the credential in every check
The conformance suite SHALL mask the run's credential in the problem of every check it reports, not only the whole
run's.

#### Scenario: A runner that echoes its key in a refusal
- **WHEN** the suite is given a credential and the runner refuses a `run/start` with a problem holding the key
- **THEN** the check's problem holds `[credential]` in place of the key

### Requirement: A malformed conformance variable is refused
The env-driven conformance check SHALL refuse a `TROUPE_CONFORMANCE_RUNNER`, `TROUPE_CONFORMANCE_OPTIONS` or
`TROUPE_CONFORMANCE_RUNTIME` that is set but malformed, naming the variable, what it must hold and the fix, never
reading it as unset.

#### Scenario: Options that aren't a JSON object
- **WHEN** `TROUPE_CONFORMANCE_OPTIONS` is set to JSON that isn't an object
- **THEN** the check fails naming `TROUPE_CONFORMANCE_OPTIONS` and that it must be a JSON object

#### Scenario: A runtime with a field config doesn't have
- **WHEN** `TROUPE_CONFORMANCE_RUNTIME` holds a field a runtime doesn't have
- **THEN** the check fails naming `TROUPE_CONFORMANCE_RUNTIME` and the field

#### Scenario: A runner command that isn't a list of strings
- **WHEN** `TROUPE_CONFORMANCE_RUNNER` is set to anything but a non-empty JSON array of strings
- **THEN** the check fails naming `TROUPE_CONFORMANCE_RUNNER` and what it must hold
