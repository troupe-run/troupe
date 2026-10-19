## MODIFIED Requirements

### Requirement: The declaration skips OpenSpec artifacts and scopes the docs
troupe SHALL declare in `scripts/check-paths.toml` that `openspec/**` needs no check. It SHALL declare a scope
`docs`, covering `docs/**`, `contributing/**` and `plugins/runner-scripted/README.md`, and the package and `scripts`
scopes that the requirements below name. Any other path SHALL be in neither group, so a change to it runs the full
check.

#### Scenario: A commit that stages only OpenSpec artifacts
- **WHEN** a commit stages only files under `openspec/`, such as an archive or a task tick
- **THEN** the commit guard skips the check, naming `openspec/**` and `scripts/check-paths.toml`

#### Scenario: A commit that stages only documentation
- **WHEN** a commit stages only files under `docs/` or `contributing/`, possibly with files under `openspec/`
- **THEN** the commit guard runs `scripts/check.py --scope docs` instead of the full check, and says so

#### Scenario: A commit that changes the scripted runner's README
- **WHEN** a commit stages only `plugins/runner-scripted/README.md`
- **THEN** the commit guard runs `scripts/check.py --scope docs --scope runner_scripted`, because the path is in both
  scopes

#### Scenario: A commit that stages anything else
- **WHEN** a commit stages a path in no scope, such as core code, a check or guard file, CI configuration, `protocol/`
  or the root `README.md`
- **THEN** the commit guard runs the full check

### Requirement: The documentation tests carry the docs tag
Every test that reads a file the `docs` scope covers SHALL be tagged `docs`. The tag SHALL go on whole modules
when every test in the module reads the docs, and on single tests otherwise, so a scoped run doesn't run tests that
read nothing the scope covers.

#### Scenario: The tests that check the docs against the code
- **WHEN** `scripts/check.py --scope docs` runs
- **THEN** the tests that compare `docs/` and `contributing/` with the code run, including the CLI reference, runs,
  runners, event store, exit codes and platform documentation tests, and the scripted runner's README options test
- **AND** the tests of the user docs' front matter, links, vocabulary, changelog page and generated regions run
- **AND** no other test runs

### Requirement: Every test run keeps the declaration true
Every pytest run in this repository, full or scoped, in one process or in parallel, SHALL fail a test that reads a file
under a scope's paths without that scope's tag, or reads a file under `openspec/`. The failure SHALL name the test, the
file, and the tag to add or the skip entry it contradicts.

#### Scenario: A new doc test without its tag
- **WHEN** a test reads `contributing/runs.md` and isn't tagged `docs`
- **THEN** that test fails, naming itself, `contributing/runs.md` and the `docs` tag

#### Scenario: A test that reads another package's files untagged
- **WHEN** a test outside the scripted runner's reach reads a file under `plugins/runner-scripted/` and isn't tagged
  `runner_scripted`
- **THEN** that test fails, naming itself, the file and the `runner_scripted` tag

#### Scenario: A test that reads OpenSpec artifacts
- **WHEN** a test reads a file under `openspec/`
- **THEN** that test fails, naming the file and the `openspec/**` skip entry

#### Scenario: An untagged doc read in a parallel run
- **WHEN** the tests run in parallel and a test in any worker reads `contributing/runs.md` without the `docs` tag
- **THEN** that test fails, naming itself, `contributing/runs.md` and the `docs` tag, as it does in one process
