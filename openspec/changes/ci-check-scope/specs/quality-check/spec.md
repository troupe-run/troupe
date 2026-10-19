# Spec Delta

## ADDED Requirements

### Requirement: A pull request's CI runs only what its changed paths need
CI SHALL work out a pull request's changed paths, from its base to its head, and ask the declaration in
`scripts/check-paths.toml` what they need, through the same decision the commit guard makes. Every leg of the test
matrix SHALL then skip the check, run the scoped check, or run the full check, as that answer says.

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

### Requirement: CI runs the full check when the changed paths are unknown
When CI can't work out a pull request's changed paths, or can't get an answer from the declaration, every leg SHALL
run the full check. A skip SHALL happen only when the changed paths are known and every one is skipped.

#### Scenario: The changed paths can't be worked out
- **WHEN** the step that lists a pull request's changed paths fails, or lists none
- **THEN** every leg runs the full check

#### Scenario: A malformed declaration
- **WHEN** a pull request makes `scripts/check-paths.toml` malformed
- **THEN** every leg runs the full check, which fails, naming the file and what is wrong with it

### Requirement: Every push to main runs the full check
A push to `main` SHALL run the full check on every leg, whatever it changed.

#### Scenario: A merge that changes only OpenSpec artifacts
- **WHEN** a pull request whose changes are all under `openspec/` merges into `main`
- **THEN** every leg runs the full check on `main`

### Requirement: One required check reports for every leg
CI SHALL report one check named `check` on every pull request and every push to `main`. It SHALL pass when every leg
passed, or when every leg was skipped because the changed paths needed no check. It SHALL fail when any leg failed or
was cancelled, and when the legs were skipped for any other reason.

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

### Requirement: No gate reads OpenSpec artifacts
No gate in `scripts/check.py` SHALL read a file under `openspec/`, so that skipping the check for a change to those
files skips nothing that could fail.

#### Scenario: A badly formatted code block in an OpenSpec artifact
- **WHEN** a Markdown file under `openspec/` holds a Python code block that ruff would reformat
- **THEN** `scripts/check.py`'s format gate passes

#### Scenario: The same block in the documentation
- **WHEN** a Markdown file under `docs/` holds the same code block
- **THEN** the format gate fails, naming the file
