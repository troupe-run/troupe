# Tasks

## 1. Core

- [ ] 1.1 Remove `lm-studio` from `troupe.core.interim.RUNNERS`, `RuntimeFit.scheme`, the `endpoint-scheme` reason and
      its messages in `troupe.core.runtimes`, the built-in in `troupe.core.defaults.RUNTIMES`, the LM Studio audition
      in `troupe.core.audition` and its note in `troupe.cli.init`. Verify: `grep -rni "lm.studio\|lmstudio"
      packages/troupe/src` finds nothing.
- [ ] 1.2 Delete `packages/troupe/tests/lm_studio_stand_in.py` and `test_lm_studio_live.py`, and the LM Studio
      conformance test. Move the uninstalled-runner and extra tests (`test_config_uninstalled.py`, `test_interim.py`,
      `test_cli_init.py`, `test_init.py`, the perform refusal) to the fixture runner `example` (design D1). Verify:
      they pass, and each fails when its rule is broken (spot-check by breaking `in_extra` handling once).
- [ ] 1.3 Update the runtime tests (`test_runtimes.py`, `test_runtime_fit.py`, `test_runtime_defaults.py`,
      `test_perform_runtime.py`, `test_run_host.py`, `test_config_kinds.py`, `test_cli_config.py`) for the specs'
      new scenarios: built-ins are `ollama` and `openai`, `lm-studio` is refused as unknown, an https endpoint fits
      `ollama`, and another runner's built-in of the same shape is refused (with a stand-in built-in). Verify: the
      core suite passes.
- [ ] 1.4 Update `packages/troupe-plugin-sdk/tests/test_runner_types.py` and `plugins/runner-ollama`'s runtime test and
      docstring that name `lm-studio`. Verify: their suites pass.

## 2. Plugin, bundle and release config

- [ ] 2.1 Delete `plugins/runner-lm-studio/`. Remove it from the root `pyproject.toml` (workspace member and source,
      mypy and coverage paths, import-linter contracts), `troupe-run`'s `lm-studio` extra and `all` (leaving `all =
      []`), `release-please-config.json`, `.release-please-manifest.json`, `scripts/check-paths.toml`'s
      `runner_lm_studio` scope and other entries, and `scripts/licences.toml`'s mention. Run `uv lock`. Verify: `uv
      lock --check` passes and `lmstudio` is gone from `uv.lock`.
- [ ] 2.2 Update the workspace tests that name LM Studio (`test_install_check.py`, `test_install_docs.py`,
      `test_plugin_imports.py`, `test_runner_licences.py`, `bundle_state.py`) to the fixture runner `example`.
      Verify: the bundle, release-config, install-docs and licence checks pass with no runner extra, and
      `scripts/tests/workspace` passes.

## 3. Docs

- [ ] 3.1 Remove LM Studio from `docs/opening-night/install.md` (extras table: `all` only),
      `docs/stagecraft/bring-your-own-agent.md`, `docs/stagecraft/runtimes.md` (built-ins, fit table, the plain-`http`
      rule, the env example), `docs/the-company/performances-and-runs.md`, `docs/backstage/changelog.md`,
      `plugins/README.md`, `contributing/runners.md` and `contributing/config.md`. Verify: `grep -rni
      "lm.studio\|lmstudio" docs contributing plugins/README.md` finds only what the runtimes page says about running
      LM Studio through a runtime of your own, and the docs checks pass.

## 4. Whole check

- [ ] 4.1 Confirm nothing else names it: `grep -rniI "lm.studio\|lmstudio\|lm_studio" --exclude-dir=.git
      --exclude-dir=.venv --exclude-dir=archive .` lists only this change, the spec it retires, and tests asserting
      `lm-studio` is refused.
- [ ] 4.2 Run `uv run scripts/check.py` (load under ~40) and record the result.

## Workflow follow-up

- infrastructure: an issue (board, 0.2.0) and change in `../track-b-14b-413-infrastructure-remove-lm-studio-purpose`
  removing `lm-studio-runner` from `oob/troupe-spec-purposes.json` only; its PR merges right after this one.
- Archive on the branch before merging (`retire_capabilities: true` deletes `openspec/specs/lm-studio-runner/`).
- After the merge, check #413 is closed and its card says Done.
