# Proposal

## Why

The release pull request #263 fails 19 tests on every CI leg, and `main` is green (#411). Each failure comes from a
test or a check that assumes the repository stays as it is today: that `troupe-runner-ollama` stays at 0.0.0, that
LM Studio and the plugin SDK stay unreleased, and that the SDK can be pinned in the same commit that first releases
it. Until those assumptions go, no release pull request that releases these components can pass, and release-please
can't publish 0.2.0.

## What Changes

- **Ollama's fixtures stop holding the runner's version.** The replay checks `init`'s `runner.version` against the
  installed `troupe-runner-ollama`, then compares it as `<package version>`, as the OpenAI runner's replay already
  does. Each fixture's `events.json` gets `<package version>` in place of `0.0.0`. The spec doesn't change: a
  replayed fixture still gives exactly its events.
- **The workspace tests build the release states they need** (pin-tests-any-state D1, #229). The tests in
  `scripts/tests/workspace/test_bundle.py` and `test_release_config.py` that write or expect `troupe-runner-lm-studio`
  bare take its requirement from the copy instead, whatever it is. A test that needs the SDK unreleased says so in
  its copy. They pass on `main`, in #263's state and in the state the pinning pull request after it leaves.
- **The bundle check no longer refuses a component's first release before its pin** (the owner's decision on #411,
  2026-11-13: option A). The installation requirement "A pinned component's released workspace dependencies
  are pinned too" (runner-sdk D12) is removed, with `_unpinned_dependencies` in `scripts/bundle.py` and its tests.
  The releases spec's rule from #262 already keeps a bundle that names any member bare from releasing, so a
  `troupe-run` tag still can't name the SDK bare.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `installation`: removes "A pinned component's released workspace dependencies are pinned too".
- `releases`: "The bundle's extras are pinned like its dependencies" is re-added as "The bundle's extras follow
  its dependencies' rules", without that rule, and with a scenario for a component's first release before its pin.

## Impact

- `plugins/runner-ollama/tests/fixture_replay.py` and every `plugins/runner-ollama/tests/fixtures/ollama/*/events.json`.
- `scripts/tests/workspace/test_bundle.py` and `test_release_config.py`, and maybe `scripts/tests/bundle_state.py`.
- `scripts/bundle.py` and `openspec/specs/installation/spec.md`. Removing or changing a requirement doesn't change
  the spec's Purpose, so infrastructure's out-of-band record (`oob/troupe-spec-purposes.json`) needs nothing.
- No change to `release-please-config.json`, `pin_bundle.py` or the release workflow. Once this merges,
  release-please regenerates #263 on `main`'s next push. Its first pinning pull request is #274's first step.
