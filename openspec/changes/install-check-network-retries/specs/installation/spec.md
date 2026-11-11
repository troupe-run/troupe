## ADDED Requirements

### Requirement: The install check outlasts a short network outage
The install check SHALL retry a failed connection to a package index for longer than uv does by default, with the
number of retries named in one place, so a short outage on one runner doesn't fail it. A failure that isn't a network
fault, such as a package the index doesn't have, SHALL still fail it without waiting, naming the step and uv's output.

#### Scenario: An index that fails more often than uv's default retries allow
- **WHEN** the package index answers the install's first four requests to it with an error a retry can recover from,
  then serves them
- **THEN** the install succeeds

#### Scenario: A package that doesn't resolve
- **WHEN** a requirement names a package the index doesn't have
- **THEN** the install fails after the index's one answer for that package, without asking again, naming the install
  step and uv's output

#### Scenario: An outage longer than the retries allow
- **WHEN** the package index fails every request for longer than the retries can outlast
- **THEN** the install fails, naming the install step and uv's output

### Requirement: The caller's own retry setting is kept
When whoever runs the install check has set uv's retry count in the environment, the check SHALL pass that value to uv
unchanged rather than its own. A value uv can't read SHALL fail the install step, naming the variable and the value,
not fall back to the check's own.

#### Scenario: A retry count set by the caller
- **WHEN** the install check runs with `UV_HTTP_RETRIES=1` in its environment
- **THEN** each `uv tool install` it runs gets `UV_HTTP_RETRIES=1`

#### Scenario: A malformed retry count
- **WHEN** the install check runs with `UV_HTTP_RETRIES=abc` in its environment
- **THEN** the install check fails at the install step, and its output names `UV_HTTP_RETRIES` and `abc`
