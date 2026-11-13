# Tasks

The three states named below are the real files as they are on `main`, as #263's branch (21060ecc) leaves them, and
as the pinning pull request after it leaves them (`pin_bundle.py` applied to #263's state). Each is checked in a
scratch copy of the repository with its own `uv sync`, or by copying the real files aside and restoring them (never
`git stash`).

## 1. Ollama's fixtures don't hold the runner's version (design D1)

- [x] 1.1 In `plugins/runner-ollama/tests/fixture_replay.py`, check `init`'s `runner.version` against the installed
  `troupe-runner-ollama` and replace it with `<package version>`, as `openai_fixture_replay.py` does. Verify: the
  fixture test fails on every run fixture before the fixtures change (showing the replay compares the placeholder).
  The capture tool writes the placeholder too, and `test_ollama_capture.py` checks it (fails when the capture keeps
  the real version).
- [x] 1.2 Replace `"version": "0.0.0"` in each run fixture's `events.json` `init` event's `runner` with
  `"<package version>"`, and nothing else. Verify: `git diff --stat` touches only the 11 run fixtures' `events.json`,
  one line each, and `uv run pytest plugins/runner-ollama/tests/test_ollama_fixtures.py` passes on `main` and with
  the plugin's version set to 0.1.0 (#263's state).

## 2. Workspace tests keep the copy's real extras, whatever they hold (design D2)

- [ ] 2.1 In `scripts/tests/workspace/test_bundle.py` and `test_release_config.py`, replace `LM_STUDIO` and
  `with_lm_studio` with a helper that keeps the copy's real extras as they are (any runners, bare or pinned, or none)
  beside the fixture runner `example`. Turn `test_the_bundle_has_the_lm_studio_extra_and_all_naming_it` into a check
  of the real extras against core's runner table. No new test names a specific real runner. Verify: the 6 extras
  failures from #263 pass in all three states. Each changed test still fails when its broken property is reverted
  (one mutation per test, noted in the commit). The tests also pass with LM Studio's extra and its table entry
  removed from a copy (the state #413 will leave).

## 3. Remove the pinned-dependency rule (design D3, D4; the owner chose option A on #411, 2026-11-13)

- [ ] 3.1 Remove `_unpinned_dependencies` and its call from `scripts/bundle.py`, and the docstring sentence naming
  the rule. Remove the tests of it in `test_bundle.py` (`test_a_pinned_core_with_the_released_sdk_bare_names_both_and_the_bundle`,
  the adapter-pinned-troupe-bare test, `test_a_pinned_extra_runner_with_the_released_sdk_bare_names_both`, and any
  that only show it passing). Add a test for the releases scenario "A component's first release before its pin":
  the SDK at 0.1.0, core pinned, the SDK bare, the exclusion present, no problems. Add a test that the same copy
  without the exclusion (a bundle that could release) is refused by the check, naming the SDK, the config file and
  the exclusion to add. Verify: the new test fails before
  the removal and passes after it, and `test_troupe_run_installs_troupe_with_every_workspace_member` passes in all
  three states.
- [ ] 3.2 Update the comment in `test_release_config.py` that quotes "The bundle's extras are pinned like its
  dependencies" to the new name, and check `contributing/releasing.md` and `docs/` name the rule nowhere (`git grep`).
  Verify: `git grep -n "pinned like its dependencies\|released workspace dependencies"` finds only archived changes
  and this change.

## 4. Integration

- [ ] 4.1 Run `scripts/tests/workspace/`, `scripts/tests/test_release_workflow.py` and the Ollama plugin's tests in
  each of the three states. Verify: all pass, and the result for each state is recorded in the PR's verification
  section.
- [ ] 4.2 `openspec validate release-pr-checks --strict` passes, and `uv run scripts/check.py` passes on the branch
  (full log kept in a scratch file). Load under ~40 before the full run.

## Workflow follow-up

- Draft PR closing #411, then act on Claude's review, mark it ready, and archive on the branch before the owner merges.
- After the merge, check that release-please rebuilt #263 and that its CI passed. Report it on #411 and to the
  orchestrator.
