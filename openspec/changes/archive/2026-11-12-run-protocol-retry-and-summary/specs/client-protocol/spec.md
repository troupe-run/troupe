## ADDED Requirements

### Requirement: A run summary that hasn't ended carries nothing from the run's end
A run summary whose `state` isn't `ended` SHALL carry no `transcript`, `transcriptFormat`, `stderr`, `error` or
`recording`, since troupe takes each from the run's end. The client protocol's run schema SHALL refuse such a summary,
and reading one SHALL fail, naming the field.

#### Scenario: A running run with a transcript
- **WHEN** a run summary has state `running` and a `transcript` and `transcriptFormat`
- **THEN** it doesn't validate against the client protocol's run schema, and reading it fails, naming `transcript`

#### Scenario: An interrupted run with standard error
- **WHEN** a run summary has state `interrupted` and a `stderr`
- **THEN** it doesn't validate against the client protocol's run schema, and reading it fails, naming `stderr`

#### Scenario: An unfinished run elsewhere with an error or a recording failure
- **WHEN** a run summary has state `unfinished-elsewhere` and an `error`, or a `recording`
- **THEN** it doesn't validate against the client protocol's run schema, and reading it fails, naming the field

#### Scenario: What troupe reports for a run that hasn't ended
- **WHEN** `status` reports a run whose `perform` is still alive
- **THEN** its summary carries none of `transcript`, `transcriptFormat`, `stderr`, `error` and `recording`, and
  validates against the client protocol's run schema
