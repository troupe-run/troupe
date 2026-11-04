## ADDED Requirements

### Requirement: A run summary carries its run's audit
A run summary SHALL carry `audit`, exactly as the run's end recorded it, when the end recorded one. It SHALL leave
`audit` out for a run that hasn't ended, one whose runner never started, and one whose end was recorded before audits
were.

#### Scenario: A failed run's summary
- **WHEN** `status` reports a run that failed after changing `src/a.py` outside its declaration
- **THEN** its summary's `audit.outside` names `src/a.py`, what happened to it and the effect it needed

#### Scenario: A running run's summary
- **WHEN** `status` reports a run whose `perform` is still alive
- **THEN** its summary has no `audit`

#### Scenario: A summary whose audit has both findings and an error
- **WHEN** a run summary's `audit` has both `outside` and `error`
- **THEN** it doesn't validate against the client protocol's run schema
