# Spec Delta

## MODIFIED Requirements

### Requirement: The effect check is not enforcement
A passing post-run effect check, including its audit of the run's changes against the declared effects, and a
runner's applying of those effects, SHALL NOT make a run's effects count as enforced. A run's admission and its effect
check verdict SHALL be recorded separately.

#### Scenario: A passing effect check on the local stage
- **WHEN** a run on the local stage succeeds with its effect check passing
- **THEN** its lineage still says its effects were `unenforced`

#### Scenario: A runner that checked every call
- **WHEN** a run on the local stage, whose runner's `init` reports `effects` as `checked`, succeeds with its audit
  passing
- **THEN** its lineage still says its effects were `unenforced`
