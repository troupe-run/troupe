# Tasks

## 1. Reproduce

- [x] 1.1 Parametrize the `copy` fixture in `scripts/tests/workspace/test_release_config.py` with `as-is` and `released` (design D3): `released` bumps every version in the copy's `.release-please-manifest.json` to its next minor and sets the copy's recorded protocol version to the bumped protocol version. Leave the tests themselves unchanged. Verify the reproduction: `uv run pytest scripts/tests/workspace/test_release_config.py` passes every `as-is` case and fails exactly the six cases #188 names, each only under `released`, with the same `0.1.0` vs `0.0.0` mismatch as run 40854801952; `test_the_copy_of_the_real_files_has_no_problems[released]` passes (the bumped copy is consistent)

## 2. Fix

- [x] 2.1 Add a `released(copy)` helper that reads the protocol's version from the copy's manifest (design D1), and build the expected messages of `test_a_missing_record_is_named_with_the_manifests_version` and `test_a_record_that_doesnt_hold_only_a_version_is_named` from it. Verify those five cases pass under both `as-is` and `released`
- [x] 2.2 In `test_a_record_that_differs_from_the_manifest_names_both_files_and_versions`, write the next major after the manifest's version as the record (design D2), assert it differs from the manifest's before using it, and build the expected message from both. Verify the test passes under both `as-is` and `released`, and that `git grep -n '0\.2\.0' scripts/tests/workspace/test_release_config.py` returns nothing
- [x] 2.3 Verify the whole file passes: `uv run pytest scripts/tests/workspace/test_release_config.py`, every case under both ids, and `test_every_workspace_member_is_configured_for_release` on the real repository

## 3. Check against the release pull request

- [x] 3.1 Run the fixed test file on the release pull request's files (design, "Risks"): add a throwaway worktree of `origin/release-please--branches--main` (#89's head) under the scratchpad, copy the fixed `test_release_config.py` into it, and run `uv run pytest scripts/tests/workspace/test_release_config.py` there. Verify every case passes, so the change unblocks #89; record the head SHA it ran on in the PR description. Remove the throwaway worktree afterwards
- [x] 3.2 Run `uv run scripts/check.py`, and verify all gates pass

## Workflow follow-up

- Open the PR with `Closes #188`; CI must pass on Linux, macOS and Windows.
- Once it merges, the release pull request (#89) needs its `check` re-run (or release-please to rebase it onto main) to pick up the fixed tests.
- Archive the change on the branch (`/opsx:archive`) before merging. There are no delta specs to sync.
- After the merge, comment on #188 with the PR and the archived change, and check its card on the roadmap board says Done.
