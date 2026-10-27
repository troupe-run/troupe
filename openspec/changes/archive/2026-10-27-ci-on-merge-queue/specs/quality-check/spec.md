## ADDED Requirements

### Requirement: Every merge group runs the full check
CI SHALL run on every merge group the merge queue creates for `main`, and SHALL run the full check there on every
leg, whatever its pull requests changed. No trigger filter or changed-path answer SHALL skip or narrow the check on a
merge group, since the queue lands only a commit whose required checks reported on it.

#### Scenario: A merge group of pull requests that change only OpenSpec artifacts
- **WHEN** the merge queue builds a merge group from pull requests whose changes are all under `openspec/`
- **THEN** every leg runs the full check on the merge group's commit
- **AND** `check` reports on that commit

#### Scenario: A merge group of pull requests that change code
- **WHEN** the merge queue builds a merge group from a pull request that changes core code
- **THEN** every leg runs the full check on the merge group's commit, and `check` passes only when every leg passed

#### Scenario: The workflow gains a path filter
- **WHEN** a change adds a path filter to any of CI's triggers, or lets the job that works out changed paths run on a
  merge group
- **THEN** the full check fails, naming the workflow and what would skip the check on the queue

## MODIFIED Requirements

### Requirement: One required check reports for every leg
CI SHALL report one check named `check` on every pull request, every merge group and every push to `main`. It SHALL
pass when every leg passed, or when every leg was skipped because the changed paths needed no check. It SHALL fail
when any leg failed or was cancelled, and when the legs were skipped for any other reason.

#### Scenario: Every leg passes
- **WHEN** every leg runs and passes
- **THEN** `check` passes

#### Scenario: One leg fails
- **WHEN** every leg runs and one fails
- **THEN** `check` fails

#### Scenario: The legs are skipped because nothing needs checking
- **WHEN** the changed paths are all skipped, and so every leg is skipped
- **THEN** `check` passes

#### Scenario: The legs are skipped without that answer
- **WHEN** every leg is skipped, but the answer wasn't that nothing needs checking
- **THEN** `check` fails, saying the legs were skipped without a reason to skip them

#### Scenario: A merge group's legs pass
- **WHEN** every leg runs the full check on a merge group's commit and passes
- **THEN** `check` passes on that commit
