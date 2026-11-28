## MODIFIED Requirements

### Requirement: Every test run shares one Hypothesis example database
Every pytest run of the repository's tests under Hypothesis's `default` profile SHALL save and replay examples in one
database, `.hypothesis/examples` at the repository root, whichever directory pytest is started from. When
`HYPOTHESIS_STORAGE_DIRECTORY` is set, Hypothesis SHALL use that directory instead. The `ci` profile SHALL keep no
database.

#### Scenario: A failure found from a package directory
- **WHEN** a Hypothesis test fails in a run started from `packages/troupe`
- **THEN** the check, run from the repository root, replays the saved example and fails

#### Scenario: A failure found from the root
- **WHEN** a Hypothesis test fails in a run started from the repository root
- **THEN** a run started from `packages/troupe` replays the saved example and fails

#### Scenario: A storage directory set in the environment
- **WHEN** a run has `HYPOTHESIS_STORAGE_DIRECTORY` set, as each flake hunt round does
- **THEN** its examples go to that directory, and the repository's database is unchanged

#### Scenario: A mutation tool's copy of a checkout under another directory
- **WHEN** the repository is checked out under another directory, and its tests run from a mutation tool's copy with
  the checkout's entries linked beside it, as the nightly mutation run lays them out
- **THEN** the database is the checkout's `.hypothesis/examples`, and the tests that check where it is pass
