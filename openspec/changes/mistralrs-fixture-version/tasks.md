# Tasks

## 1. Reproduce the release failure

- [ ] 1.1 Bump `plugins/runner-mistralrs/pyproject.toml` to `0.1.0` locally (as release-please does), re-sync, and
  confirm the four `test_a_fixture_replayed_gives_exactly_its_events_and_transcript_kinds` cases fail on the runner
  version. Put the version back and re-sync.

## 2. Fix the replay and the capture tool

- [ ] 2.1 In `test_mistralrs_fixtures.py`, check the `init` event's runner version against the installed
  `troupe-runner-mistralrs` version, then compare it as `<package version>` (design D1)
- [ ] 2.2 Replace `"version": "0.0.0"` under `runner` with `"<package version>"` in the four fixtures'
  `expected.json`, leaving the engine's `0.9.5` alone
- [ ] 2.3 Make `tools/capture_mistralrs.py` write `<package version>` for the runner version, and update its docstring
  (design D2)

## 3. Verify

- [ ] 3.1 The mistral.rs plugin's tests pass at `0.0.0`
- [ ] 3.2 With the version bumped to `0.1.0` again, the four cases pass. Put the version back and re-sync, and check
  `git status` shows no version change
- [ ] 3.3 With the runner made to report a wrong version, the replay fails on the version check, not on the comparison
- [ ] 3.4 `uv run scripts/check.py` passes

## Workflow follow-up

- Draft PR closing #468 (not #263), act on Claude's review, mark it ready, run `/openspec-archive-change` on the branch
- After the merge, release-please regenerates #263 from main. Check #263's CI passes.
