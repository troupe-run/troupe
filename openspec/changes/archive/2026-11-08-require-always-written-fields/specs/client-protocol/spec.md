## MODIFIED Requirements

### Requirement: A run summary carries its run's audit
A run summary SHALL carry `audit`, exactly as the run's end recorded it, exactly when the run has ended and its runner
started, that is when its state is `ended` and it carries a `transcript`. It SHALL leave `audit` out for a run that
hasn't ended and for one whose runner never started.

#### Scenario: A failed run's summary
- **WHEN** `status` reports a run that failed after changing `src/a.py` outside its declaration
- **THEN** its summary's `audit.outside` names `src/a.py`, what happened to it and the effect it needed

#### Scenario: A running run's summary
- **WHEN** `status` reports a run whose `perform` is still alive
- **THEN** its summary has no `audit`

#### Scenario: A summary whose audit has both findings and an error
- **WHEN** a run summary's `audit` has both `outside` and `error`
- **THEN** it doesn't validate against the client protocol's run schema

#### Scenario: A summary that leaves out its audit
- **WHEN** a run summary has state `ended` and a `transcript`, and no `audit`
- **THEN** it doesn't validate against the client protocol's run schema, and the SDK refuses to read it, naming
  `audit`

#### Scenario: An audit without a runner that started
- **WHEN** a run summary has state `ended`, no `transcript`, and an `audit`
- **THEN** it doesn't validate against the client protocol's run schema
