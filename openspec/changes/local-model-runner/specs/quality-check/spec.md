# Spec Delta

## MODIFIED Requirements

### Requirement: Each package outside core has a scope
troupe SHALL declare one scope per workspace package other than core: `artifacts_local`, `identity_local`,
`stage_local`, `store_text`, `vcs_files`, `vcs_git`, `plugin_sdk` and `run` for `packages/troupe-<name>/`, and
`runner_claude_code`, `runner_ollama` and `runner_scripted` for `plugins/runner-<name>/`. Each SHALL cover its
package's files except `pyproject.toml`. Core (`packages/troupe/**`) and every `pyproject.toml` SHALL be in no scope,
so a change to them runs the full check.

#### Scenario: A commit that changes one leaf package
- **WHEN** a commit stages only files under `packages/troupe-stage-local/`, possibly with files under `openspec/`
- **THEN** the commit guard runs `scripts/check.py --scope stage_local`
- **AND** every gate runs, and the tests that run are the stage-local suite and the suites that reach it

#### Scenario: A commit that changes two packages
- **WHEN** a commit stages files under `packages/troupe-vcs-git/` and `packages/troupe-store-text/`
- **THEN** the commit guard runs `scripts/check.py --scope store_text --scope vcs_git`, and the tests that run are
  every suite that reaches either package

#### Scenario: A commit that changes core
- **WHEN** a commit stages any file under `packages/troupe/`, including core's shared test helpers
- **THEN** the commit guard runs the full check

#### Scenario: A commit that changes a package's pyproject.toml
- **WHEN** a commit stages `packages/troupe-stage-local/pyproject.toml`, which can change the package's dependencies
  or entry points and so what reaches it
- **THEN** the commit guard runs the full check

#### Scenario: A package added later
- **WHEN** a commit adds a new directory under `packages/` or `plugins/` that no scope names
- **THEN** the commit guard runs the full check

#### Scenario: A commit that changes the plugin SDK
- **WHEN** a commit stages only files under `packages/troupe-plugin-sdk/src/`
- **THEN** the commit guard runs `scripts/check.py --scope plugin_sdk`, and the tests that run are the SDK's suite
  and every suite that reaches it, core's and every runner's among them

#### Scenario: A commit that changes the Ollama runner
- **WHEN** a commit stages only files under `plugins/runner-ollama/src/`
- **THEN** the commit guard runs `scripts/check.py --scope runner_ollama`, and the tests that run are the Ollama
  runner's suite and the suites that reach it
