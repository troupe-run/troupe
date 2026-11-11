## MODIFIED Requirements

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

#### Scenario: Tests from several packages selected by node id
- **WHEN** a developer runs pytest on tests from the git adapter's and the Ollama runner's suites, each named by its
  node id, in one process or across workers, and neither test reads the other package's files itself
- **THEN** both tests pass with no guard failure, although collecting them imported both suites' modules

#### Scenario: A real untagged read in a selection by node id
- **WHEN** the same kind of selection also names a test that reads `contributing/runs.md` without the `docs` tag
- **THEN** that test fails, naming itself, `contributing/runs.md` and the `docs` tag, and the other selected tests pass
