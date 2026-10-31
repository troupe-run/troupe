## ADDED Requirements

### Requirement: A push to main skips a commit the merge queue passed
On a push to `main`, CI SHALL skip every leg when its own merge-queue run on that exact commit succeeded, and `check`
SHALL pass. Any other push to `main` SHALL run the full check on every leg. Finding out SHALL never fail CI's run:
when it can't be found out, every leg runs the full check.

#### Scenario: A merge through the queue
- **WHEN** the merge queue passes a merge group and its commit lands on `main`
- **THEN** CI's run on `main` runs no leg, `check` passes, and the run succeeds

#### Scenario: A commit that didn't come through the queue
- **WHEN** a commit reaches `main` with no merge-queue run of CI on it, such as a guard delivery
- **THEN** every leg runs the full check on `main`

#### Scenario: A merge-queue run on the commit that didn't pass
- **WHEN** CI's only merge-queue runs on the commit pushed to `main` failed or were cancelled
- **THEN** every leg runs the full check on `main`

#### Scenario: The merge-queue run is still finishing
- **WHEN** CI's merge-queue run on the commit hasn't completed when the push's run asks
- **THEN** CI waits for it for a bounded time, skips the legs if it succeeds in that time, and otherwise runs the full
  check

#### Scenario: The merge-queue runs can't be read
- **WHEN** reading CI's merge-queue runs fails, or answers in a shape CI doesn't recognise
- **THEN** CI warns, naming why, and every leg runs the full check
- **AND** the read itself doesn't fail the run

### Requirement: A draft pull request runs no legs until it's marked ready
On a draft pull request, CI SHALL run no leg, and `check` SHALL be skipped rather than pass. Marking the pull request
ready for review SHALL run what every path the pull request changes from its base needs.

#### Scenario: A push to a draft
- **WHEN** a draft pull request is opened, or a push adds to one, whatever it changes
- **THEN** no leg installs the project or runs `scripts/check.py`
- **AND** `check` is skipped, saying it runs when the pull request is marked ready

#### Scenario: A draft marked ready
- **WHEN** a draft whose changes include core code is marked ready for review
- **THEN** every leg runs the full check, judged on every path the pull request changes from its base

#### Scenario: A draft marked ready whose changes are all OpenSpec artifacts
- **WHEN** a draft whose changes are all under `openspec/` is marked ready for review
- **THEN** no leg runs `scripts/check.py`, and `check` passes

## MODIFIED Requirements

### Requirement: A pull request's CI runs only what its changed paths need
CI SHALL work out the changed paths of a pull request that's ready for review, since the last push whose `check`
passed, or from its base when no earlier push passed, and ask the declaration in `scripts/check-paths.toml` what they
need, through the same decision the commit guard makes. Every leg of the test matrix SHALL then skip the check, run the
scoped check, or run the full check, as that answer says.

#### Scenario: A pull request that changes only OpenSpec artifacts
- **WHEN** a pull request's changes are all under `openspec/`, such as a change's archive and its task ticks
- **THEN** no leg installs the project or runs `scripts/check.py`
- **AND** every required check passes

#### Scenario: A pull request that changes only documentation
- **WHEN** a pull request's changes are all under `docs/`, possibly with files under `openspec/`
- **THEN** every leg runs `scripts/check.py --scope docs`

#### Scenario: A pull request that changes two packages
- **WHEN** a pull request changes files under `packages/troupe-vcs-git/` and `packages/troupe-store-text/` only
- **THEN** every leg runs `scripts/check.py --scope store_text --scope vcs_git`

#### Scenario: A pull request that changes anything else
- **WHEN** a pull request changes a path in no group, such as core code, CI configuration, `scripts/check-paths.toml`
  or the root `README.md`
- **THEN** every leg runs the full check

### Requirement: A push is checked against the last push that passed
When a push adds to an open pull request and the latest `check` on the previous head, reported by GitHub Actions,
passed, CI SHALL work out the changed paths by comparing the previous head's tree with the new head's. Otherwise it
SHALL use every path the pull request changes from its base.

#### Scenario: An archive push after a green code push
- **WHEN** a pull request's code changes passed `check`, and the next push only moves files under `openspec/`
- **THEN** no leg installs the project or runs `scripts/check.py`
- **AND** every required check passes

#### Scenario: A push after a run that didn't pass
- **WHEN** the previous head's `check` failed, was cancelled, hasn't finished or never ran, and the next push changes
  only files under `openspec/`
- **THEN** CI uses every path the pull request changes, and runs the check those paths need

#### Scenario: A docs-only push after a green code push
- **WHEN** a pull request's code changes passed `check`, and the next push changes only files under `docs/`
- **THEN** every leg runs `scripts/check.py --scope docs`

#### Scenario: A force push
- **WHEN** a pull request whose head passed `check` is force-pushed with a rewritten history, and the new head's tree
  differs from the old one only under `openspec/`
- **THEN** no leg runs `scripts/check.py`, and every required check passes

#### Scenario: The previous head is gone
- **WHEN** the previous head can't be found in the repository
- **THEN** CI uses every path the pull request changes

#### Scenario: A check of the same name from another app
- **WHEN** the previous head has a passing check named `check` reported by an app other than GitHub Actions, and none
  from GitHub Actions
- **THEN** CI uses every path the pull request changes

#### Scenario: The previous head was only checked as a draft
- **WHEN** a draft is marked ready, and a push that changes only files under `openspec/` arrives before the ready
  run's `check` on the previous head has reported
- **THEN** CI uses every path the pull request changes, and runs the check those paths need

#### Scenario: The previous head passed once it was ready
- **WHEN** a draft was marked ready and the ready run's `check` passed on its head, and the next push changes only
  files under `openspec/`
- **THEN** no leg runs `scripts/check.py`, and every required check passes

### Requirement: One required check reports for every leg
CI SHALL report one check named `check` on every pull request that's ready for review, every merge group and every
push to `main`. It SHALL pass when every leg passed, or when every leg was skipped because the changed paths needed no
check or the merge queue had passed the commit. It SHALL fail when any leg failed or was cancelled, and when the legs
were skipped for any other reason.

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

#### Scenario: A push to main the merge queue passed
- **WHEN** every leg is skipped on a push to `main` because the merge queue passed that commit
- **THEN** `check` passes

## REMOVED Requirements

### Requirement: Every push to main runs the full check
**Reason**: The merge queue now tests the exact commit that lands on `main`, so a full run on the push repeats it
(troupe-run/infrastructure#227, #204).
**Migration**: "A push to main skips a commit the merge queue passed" replaces it: a commit the queue didn't pass
still runs the full check on `main`.
