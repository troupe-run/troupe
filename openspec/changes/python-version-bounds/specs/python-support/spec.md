# Spec Delta

## Purpose

Which Python versions troupe supports, how that support is declared and enforced, and how the declaration stays
exactly in step with the versions CI tests.

## ADDED Requirements

### Requirement: The supported versions are exactly the versions CI tests
troupe SHALL support a contiguous range of Python minor versions, declared as a lower and an upper bound of the form
`>=3.X,<3.Y`. The supported versions SHALL be exactly the Python versions in CI's test matrix, no more and no fewer.

#### Scenario: The bound and the CI matrix agree
- **WHEN** the declared bound is `>=3.12,<3.14`
- **THEN** CI's test matrix lists exactly 3.12 and 3.13

#### Scenario: A version added to CI without widening the bound
- **WHEN** 3.14 is added to CI's matrix but the bound still says `<3.14`
- **THEN** `scripts/check.py` fails, naming `.github/workflows/ci.yml` and the declared bound

#### Scenario: A bound widened without adding the version to CI
- **WHEN** the bound is widened to `<3.15` but CI's matrix still lists only 3.12 and 3.13
- **THEN** `scripts/check.py` fails, naming `.github/workflows/ci.yml` and the missing 3.14

### Requirement: Every package declares the same bound
Every workspace member and the workspace root SHALL declare the same `requires-python` bound. A member that differs,
or a bound that isn't of the form `>=3.X,<3.Y`, SHALL fail the repository's check, naming the file and the expected
value.

#### Scenario: A member with a different bound
- **WHEN** `plugins/runner-scripted/pyproject.toml` says `>=3.12` and the root says `>=3.12,<3.14`
- **THEN** `scripts/check.py` fails, naming `plugins/runner-scripted/pyproject.toml` and `>=3.12,<3.14`

#### Scenario: A bound with no upper limit
- **WHEN** the root's `requires-python` is `>=3.12`
- **THEN** `scripts/check.py` fails, naming `pyproject.toml` and the form a bound must take

### Requirement: An unsupported interpreter is refused
Running or syncing troupe from source on a Python outside the declared bound SHALL be refused, with a message naming
the bound, rather than going ahead on that interpreter.

#### Scenario: Running on a newer Python
- **WHEN** a developer runs `uv run --python 3.14 scripts/check.py` while the bound is `>=3.12,<3.14`
- **THEN** the command is refused, and the message names `>=3.12, <3.14`

### Requirement: The lowest supported version is the default
With no version requested, a developer's commands SHALL run on the lowest supported version. The tools that check
code for a target version (the linter's target and the type checker's version) SHALL also target the lowest
supported version. A default or target that differs SHALL fail the repository's check, naming the file.

#### Scenario: Plain uv run
- **WHEN** a developer runs `uv run scripts/check.py` on a machine with 3.12, 3.13 and 3.15 installed
- **THEN** it runs on 3.12

#### Scenario: A default pinned above the lowest
- **WHEN** `.python-version` says `3.13` while the bound is `>=3.12,<3.14`
- **THEN** `scripts/check.py` fails, naming `.python-version` and `3.12`

### Requirement: Any supported version can be selected in one command
A developer SHALL be able to run any command on any supported version with a single command that names the version.
Each version SHALL have its own environment, so switching versions doesn't rebuild or overwrite another version's
environment. A version outside the bound SHALL be refused, and the refusal SHALL list the supported versions.

#### Scenario: Checking on another supported version
- **WHEN** a developer runs `uv run scripts/on.py 3.13 scripts/check.py`
- **THEN** the check runs on 3.13, in an environment separate from the default one

#### Scenario: Switching back and forth
- **WHEN** a developer runs a command on 3.13 and then on 3.12, then on 3.13 again
- **THEN** each version's environment is still there, and neither is rebuilt for the switch

#### Scenario: Selecting an unsupported version
- **WHEN** a developer runs `uv run scripts/on.py 3.15 scripts/check.py` while the bound is `>=3.12,<3.14`
- **THEN** nothing runs, and the refusal names 3.15, lists 3.12 and 3.13, and names the bound

#### Scenario: A malformed version
- **WHEN** a developer runs `uv run scripts/on.py 3.x scripts/check.py`
- **THEN** nothing runs, and the refusal names `3.x` and shows the form a version takes (`3.13`)
