# Spec Delta

## ADDED Requirements

### Requirement: Lineage records the stage and whether effects were enforced
Lineage SHALL record `stage`: null for an event recorded outside a stage, or the stage's name and whether the actor's
effects were `enforced` or `unenforced`. An unenforced stage SHALL name the policy setting, and its source, that
allowed it; an enforced one SHALL name none.

#### Scenario: An event recorded outside a stage
- **WHEN** a command records an event that isn't part of a run
- **THEN** its lineage has `stage` null

#### Scenario: A run on the local stage
- **WHEN** a run on the local stage, allowed by `allow_unenforced_local_stage` from `env`, records an event
- **THEN** its lineage's `stage` names `local`, effects `unenforced`, and the setting and source that allowed it

#### Scenario: Unenforced without an allowance is refused
- **WHEN** an event is recorded with a `stage` whose effects are `unenforced` and that names nothing that allowed it
- **THEN** recording fails with `events.lineage-invalid`, and nothing is written

#### Scenario: Stage is never missing
- **WHEN** an event is recorded with lineage that has no `stage` field
- **THEN** recording fails with `events.lineage-invalid`
