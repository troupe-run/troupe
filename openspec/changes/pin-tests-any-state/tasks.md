# Tasks

## 1. Build the states, and reproduce on main

- [ ] 1.1 Add `scripts/tests/workspace/bundle_state.py` with `unpinned(root)` and `pinned(root)` (design D1): bytes in, bytes out; dependency lines found by `release_config.requirement_name`; the bundle's path from `release_config.bundle_member`, with no member path written as a literal; `unpinned` restores the bootstrap line after the entry's `"component"` line, asserting that line occurs once, and sets the bundle to `0.0.0` when the copy has a manifest; `pinned` runs `pin_bundle.apply(root, pin_bundle.moves(root))`. Verify `uv run mypy --strict` and `uv run ruff check` are clean on it
- [ ] 1.2 Parametrize `test_bundle.py`'s `copy` with `bundle` = `unpinned` / `pinned` (design D2), copying the config and manifest into it; leave the tests unchanged. Verify the reproduction on `main`: `uv run pytest scripts/tests/workspace/test_bundle.py` passes every `unpinned` case and fails exactly #229's three `test_bundle.py` tests, each only under `pinned`, with the same "isn't in packages/troupe-run/pyproject.toml" assertion as on #228
- [ ] 1.3 Add the same `bundle` dimension to `test_release_config.py`'s `copy`, applied before the `released` step (design D2); leave the tests unchanged. Verify on `main`: the file fails only `test_a_member_missing_from_the_manifest_is_named_with_the_file_and_its_tags` under `pinned` (both `as-is` and `released`), with the extra "pins troupe-runner-scripted at 0.1.0" message seen on #228, and `test_the_copy_of_the_real_files_has_no_problems` passes in all four combinations

## 2. Fix the tests

- [ ] 2.1 In `test_bundle.py`, replace the three bare-line edits with name-based helpers (design D3): drop `troupe-runner-scripted`'s line, add `"troupe-vcs-svn"` after `dependencies = [`, set `troupe-vcs-git` to its pin at `0.1.1`. Rename `test_the_copy_of_the_real_files_has_no_problems` to `test_the_copy_has_no_problems` and say in its docstring which states it covers. Verify `uv run pytest scripts/tests/workspace/test_bundle.py` passes every case under both states
- [ ] 2.2 In `test_release_config.py`, make the missing-manifest test name `troupe-runner-scripted` bare in the copy before popping it from the manifest (design D6), and apply the same rename as 2.1. Verify `uv run pytest scripts/tests/workspace/test_release_config.py` passes all four combinations of every case
- [ ] 2.3 In `test_pin_bundle.py`, call `unpinned` in the `copy` fixture (design D4). Add to `test_the_first_pin_pins_every_member_and_changes_nothing_else` an assertion that the moves name every member but the bundle and that the expected text differs from `before`, and to `test_crlf_line_endings_are_kept` one that the file changed (design D5). Verify each new assertion fails when the copy is pinned first (temporarily call `pinned` after `unpinned` in the fixture, run, see them fail, revert), then `uv run pytest scripts/tests/workspace/test_pin_bundle.py` passes

## 3. Check against the pinning pull request

- [ ] 3.1 Run the fixed files on #228's files (design, "Risks"): add a throwaway worktree of #228's head (`git fetch origin pull/228/head`) under the scratchpad, merge this branch into it as CI's `pull_request` run does, and run `uv run pytest scripts/tests/workspace/test_bundle.py scripts/tests/workspace/test_pin_bundle.py scripts/tests/workspace/test_release_config.py` there. Verify every case passes (it was 11 failed, 155 passed on `afde24d`); record the head SHA it ran on in the PR description. Remove the throwaway worktree afterwards
- [ ] 3.2 Run `uv run scripts/check.py` on the branch, and verify all gates pass

## Workflow follow-up

- Open the PR as a draft with `Closes #229`; CI must pass on Linux, macOS and Windows once it's marked ready.
- Archive the change on the branch (`/opsx:archive`) before merging. There are no delta specs to sync.
- After the merge, re-run #228's CI so its `pull_request` run picks up the fixed tests, comment on #229 with the PR and the archived change, and check its card on the roadmap board says Done.
