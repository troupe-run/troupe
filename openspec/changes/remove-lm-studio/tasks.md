# Tasks

## 1. Core

- [x] 1.1 Remove `lm-studio` from `troupe.core.interim.RUNNERS`, `RuntimeFit.scheme`, the `endpoint-scheme` reason and
      its messages in `troupe.core.runtimes` and the protocol's `error.schema.json` (both copies), the built-in in
      `troupe.core.defaults.RUNTIMES`, the LM Studio audition in `troupe.core.audition` and its note in
      `troupe.cli.init`. Verify: `grep -rni "lm.studio\|lmstudio" packages/troupe/src` finds only citations of the
      archived lmstudio-runner design, for the built-in rule that stays (three citations)
- [x] 1.2 Delete `packages/troupe/tests/lm_studio_stand_in.py` and `test_lm_studio_live.py`, and the LM Studio
      conformance test. Move the uninstalled-runner and extra tests (`test_config_uninstalled.py`, `test_interim.py`,
      `test_cli_init.py`, `test_init.py`, the perform refusal) to the fixture runner `example` (design D1). Verify:
      they pass, and each fails when its rule is broken (spot-check by breaking `in_extra` handling once). (Pass; with the extra
      dropped from `installed_runner`'s refusal, 10 of them fail.)
- [x] 1.3 Update the runtime tests (`test_runtimes.py`, `test_runtime_fit.py`, `test_runtime_defaults.py`,
      `test_perform_runtime.py`, `test_run_host.py`, `test_config_kinds.py`, `test_cli_config.py`) for the specs'
      new scenarios: built-ins are `ollama` and `openai`, `lm-studio` is refused as unknown, an https endpoint fits
      `ollama`, and another runner's built-in of the same shape is refused (with a stand-in built-in). Verify: the
      core suite passes. (The changed files: 661 passed, 1 opt-in skip; with the built-in rule removed, the four
      stand-in tests fail.)
- [x] 1.4 Update `packages/troupe-plugin-sdk/tests/test_runner_types.py` and `plugins/runner-ollama`'s runtime test and
      docstring that name `lm-studio`. Verify: their suites pass. (In the run above.)

## 2. Plugin, bundle and release config

- [x] 2.1 Delete `plugins/runner-lm-studio/`. Remove it from the root `pyproject.toml` (workspace member and source,
      mypy and coverage paths, import-linter contracts), `troupe-run`'s `lm-studio` extra and `all` (leaving `all =
      []`), `release-please-config.json`, `.release-please-manifest.json`, `scripts/check-paths.toml`'s
      `runner_lm_studio` scope and other entries, and `scripts/licences.toml`'s mention. Run `uv lock`. Verify: `uv
      lock --check` passes and `lmstudio` is gone from `uv.lock`. (`uv lock` removed lmstudio, msgspec, httpx,
      httpx-ws, httpcore, h11, anyio, idna, certifi and wsproto; nothing else needs them, so `scripts/licences.toml`'s
      MPL-2.0 reason now cites lmstudio as the past case.)
- [x] 2.2 Update the workspace tests that name LM Studio (`test_install_check.py`, `test_install_docs.py`,
      `test_plugin_imports.py`, `test_runner_licences.py`, `bundle_state.py`) to the fixture runner `example`.
      Verify: the bundle, release-config, install-docs and licence checks pass with no runner extra, and
      `scripts/tests/workspace` passes. (The bundle, release-config, install-check, install-docs, plugin-import and
      licence suites: 438 passed.)

## 3. Docs

- [x] 3.1 Remove LM Studio from `docs/opening-night/install.md` (extras table: `all` and `anthropic`),
      `docs/stagecraft/bring-your-own-agent.md`, `docs/stagecraft/runtimes.md` (built-ins, fit table, the plain-`http`
      rule, the env example), `docs/the-company/performances-and-runs.md`, `docs/backstage/changelog.md`,
      `plugins/README.md`, `contributing/runners.md` and `contributing/config.md`. Verify: `grep -rni
      "lm.studio\|lmstudio" docs contributing plugins/README.md` finds only the anthropic runner's route for LM Studio
      (#415: a runtime of your own, `lm-studio-messages`); the runtimes page's OpenAI example is now a local server of
      your own, `local-openai`. The docs checks pass (`test_install_docs.py`, `test_user_docs_pages.py`: in the runs above).

## 4. Whole check

- [x] 4.1 Confirm nothing else names it: `grep -rniI "lm.studio\|lmstudio\|lm_studio" --exclude-dir=.git
      --exclude-dir=.venv --exclude-dir=archive .` lists only this change, the spec it retires, and tests asserting
      `lm-studio` is refused. (Also: the main specs this change's deltas rewrite at archive, three citations of the
      archived lmstudio-runner design in core, and `scripts/licences.toml`'s reason naming lmstudio as the past case.)
- [x] 4.2 Run `uv run scripts/check.py` (load under ~40) and record the result. (All gates passed: ruff, mypy
      --strict, import contracts, tests in 190 s, at load ~3.)

## Workflow follow-up

- infrastructure: an issue (board, 0.2.0) and change in `../track-b-14b-413-infrastructure-remove-lm-studio-purpose`
  removing `lm-studio-runner` from `oob/troupe-spec-purposes.json` only; its PR merges right after this one.
- Archive on the branch before merging (`retire_capabilities: true` deletes `openspec/specs/lm-studio-runner/`).
- After the merge, check #413 is closed and its card says Done.
