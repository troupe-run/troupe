# quality-check Specification

## Purpose

What troupe's `scripts/check.py` runs, the scoped form that narrows its tests, and troupe's declaration of which
paths need which part of the check. The commit guard and CI read that declaration, and every test run keeps it true.

## Requirements

### Requirement: The declaration skips OpenSpec artifacts and scopes the docs
troupe SHALL declare in `scripts/check-paths.toml` that `openspec/**` needs no check. It SHALL declare one scope,
`docs`, covering `docs/**` and `plugins/runner-scripted/README.md`. Any other path SHALL be in neither group, so a
change to it runs the full check.

#### Scenario: A commit that stages only OpenSpec artifacts
- **WHEN** a commit stages only files under `openspec/`, such as an archive or a task tick
- **THEN** the commit guard skips the check, naming `openspec/**` and `scripts/check-paths.toml`

#### Scenario: A commit that stages only documentation
- **WHEN** a commit stages only files under `docs/`, or `plugins/runner-scripted/README.md`, possibly with files
  under `openspec/`
- **THEN** the commit guard runs `scripts/check.py --scope docs` instead of the full check, and says so

#### Scenario: A commit that stages anything else
- **WHEN** a commit stages any other path, such as code, a test, CI configuration or the root `README.md`
- **THEN** the commit guard runs the full check

### Requirement: A scoped check runs every gate and narrows only the tests
`scripts/check.py` SHALL accept `--scope <name>`, one or more times. With scopes, it SHALL run every gate the full
check runs, in the same order, and SHALL narrow only the tests, to those tagged with any of the given scopes. Without
`--scope`, it SHALL run exactly what it runs today.

#### Scenario: The docs scope
- **WHEN** a developer runs `uv run scripts/check.py --scope docs`
- **THEN** ruff, mypy and the import contracts run as in the full check
- **AND** only the tests tagged `docs` run

#### Scenario: A scope named twice
- **WHEN** a developer runs `uv run scripts/check.py --scope docs --scope docs`
- **THEN** the check runs as it does for `--scope docs`

#### Scenario: A failing gate in a scoped check
- **WHEN** a scoped check runs and a lint, type or test gate fails
- **THEN** the check stops and fails, naming the gate, as the full check does

### Requirement: An undeclared scope is refused before any gate runs
`scripts/check.py` SHALL refuse a scope that `scripts/check-paths.toml` doesn't declare, before running any gate. The
refusal SHALL name the scope, the file, and the fix. A malformed declaration SHALL be refused the same way, with the
guard's message, never treated as absent.

#### Scenario: A mistyped scope
- **WHEN** a developer runs `uv run scripts/check.py --scope nope`
- **THEN** the check fails without running any gate, naming `nope` and `scripts/check-paths.toml`

#### Scenario: A malformed declaration with a scope requested
- **WHEN** `scripts/check-paths.toml` is malformed and a developer runs `uv run scripts/check.py --scope docs`
- **THEN** the check fails without running any gate, saying what is wrong with the file and how to fix it

### Requirement: A scope with no tagged tests passes and says so
When every other gate passes and no test is tagged with any of the requested scopes, a scoped check SHALL pass, and
SHALL say that there was nothing to test. The full check SHALL still fail if it collects no tests.

#### Scenario: No tests carry the tag
- **WHEN** `scripts/check.py --scope docs` runs, every other gate passes, and no test is tagged `docs`
- **THEN** the check passes and says no test is tagged `docs`

### Requirement: The documentation tests carry the docs tag
Every test that reads a file the `docs` scope covers SHALL be tagged `docs`. The tag SHALL go on whole modules
when every test in the module reads the docs, and on single tests otherwise, so a scoped run doesn't run tests that
read nothing the scope covers.

#### Scenario: The tests that check the docs against the code
- **WHEN** `scripts/check.py --scope docs` runs
- **THEN** the tests that compare `docs/` with the code run, including the CLI, runs, runners, event store, exit codes
  and platform documentation tests, and the scripted runner's README options test
- **AND** no other test runs

### Requirement: Every test run keeps the declaration true
Every pytest run in this repository, full or scoped, SHALL fail a test that reads a file under a `docs` path without
the `docs` tag, or reads a file under `openspec/`. The failure SHALL name the test, the file, and the tag to add or
the skip entry it contradicts.

#### Scenario: A new doc test without its tag
- **WHEN** a test reads `docs/runs.md` and isn't tagged `docs`
- **THEN** that test fails, naming itself, `docs/runs.md` and the `docs` tag

#### Scenario: A test that reads OpenSpec artifacts
- **WHEN** a test reads a file under `openspec/`
- **THEN** that test fails, naming the file and the `openspec/**` skip entry
