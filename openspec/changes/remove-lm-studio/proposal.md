# Proposal

## Why

#412 decided to remove the LM Studio runner before 0.2.0 ships (#413): its library, `lmstudio` (LM Studio's Python
SDK), has stalled, which fails #319's "maintained client library". The runner was never released, so removing it now
costs no users, but release-please's pull request (#263) would release it and its `troupe-run[lm-studio]` extra if it
stayed. The owner decided on 2026-11-14 (recorded on #413) that the built-in `lm-studio` runtime goes with it: LM
Studio users define their own runtime for the anthropic runner, which #415 documents.

## What Changes

- **BREAKING (unreleased): the `lm-studio` runner is gone.** `plugins/runner-lm-studio` is deleted, with its tests,
  fixtures and capture tools, its entry in troupe's runner table, its LM Studio audition (`troupe init --audition
  --runner lm-studio`) and init's LM Studio note, and core's LM Studio stand-in and live test. `troupe init --audition
  --runner lm-studio` and an actor on `lm-studio` are now refused with `runner.unknown`. `contextOverflowPolicy`
  (#394) and the compaction warning (#310) go with it, since nothing else has them.
- **BREAKING (unreleased): the built-in `lm-studio` runtime is gone.** troupe's built-ins are `openai`, `anthropic` and `ollama`.
  A config that names `runtimes.lm-studio` now defines a runtime of its own, wholly by config.
- **The "plain `http` only" fit rule goes too.** Only the LM Studio runner needed it (its library has no TLS). An
  actor's runtime is still refused for a credential its runner never sends, an endpoint path it can't use, or another
  runner's built-in.
- **The bundle and release config lose it.** `troupe-run`'s `lm-studio` extra goes, leaving `anthropic` (#420) as
  the one runner extra, and the only entry in `all`. Its entries in `release-please-config.json`, the
  manifest, the root `pyproject.toml` (workspace, mypy, coverage, import contracts), `uv.lock`,
  `scripts/check-paths.toml` (its `runner_lm_studio` scope) and `scripts/licences.toml` go.
- **The `lm-studio-runner` spec is retired** through a removal delta (`retire_capabilities: true`).
- **Specs that used LM Studio as their example of a runner in an extra name a fixture runner instead**, `example` in
  `troupe-run`'s `example` extra, as #411's design D2 did for the workspace tests. That covers the releases scenarios
  #411 left naming `troupe-runner-lm-studio`, and the installation, config, cli, client-protocol and runs scenarios.
  The rules don't change.
- **Docs drop it**: the install guide's extras table, "Bring your own agent", "Runtimes", "Performances and runs", the
  backstage changelog, `plugins/README.md`, and contributing's runner and config guides.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `lm-studio-runner`: retired, with every requirement removed.
- `runtimes`: the built-in `lm-studio` and its scenarios go; the plain-`http` fit rule goes; the remaining scenarios
  that named LM Studio use runtimes of their own.
- `config`: the LM Studio audition requirement is removed; the uninstalled-runner scenarios name the fixture runner.
- `cli`: init's `--runner` scenarios drop `lm-studio`; the not-installed and extra-note scenarios name the fixture
  runner.
- `client-protocol`, `runs`: the runner-in-an-extra scenarios name the fixture runner.
- `installation`, `releases`: the bundle, install-check and docs-check scenarios name the fixture runner's extra.
- `runner-protocol`: the library and licence scenarios stop naming `lmstudio`.
- `quality-check`: the `runner_lm_studio` scope goes.

## Impact

- Deleted: `plugins/runner-lm-studio/`, `packages/troupe/tests/lm_studio_stand_in.py`,
  `packages/troupe/tests/test_lm_studio_live.py`, `openspec/specs/lm-studio-runner/` (at archive).
- Core: `troupe.core.interim` (runner table, `RuntimeFit.scheme`), `troupe.core.runtimes` (the `endpoint-scheme`
  reason), `troupe.core.defaults` (the built-in), `troupe.core.audition`, `troupe.cli.init`, and their tests.
- Bundle and release: `packages/troupe-run/pyproject.toml`, `release-please-config.json`,
  `.release-please-manifest.json`, root `pyproject.toml`, `uv.lock`, `scripts/check-paths.toml`,
  `scripts/licences.toml`, and the workspace tests that name LM Studio.
- infrastructure: `oob/troupe-spec-purposes.json` loses its `lm-studio-runner` entry, in an infrastructure pull
  request merged right after this one; otherwise its drift job fails.
- Overlap: #420 (anthropic runner, merged first, so this change is rebased on it) and #414 also change the runtimes spec, `interim.py`, `defaults.py`, the bundle and
  the docs; whichever merges second rebases.
