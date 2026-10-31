# Tasks

## 1. The check takes the group from what the bundle ships (design D1–D4)

- [ ] 1.1 Move `normalise` and `requirement_name` from `scripts/bundle.py` to `scripts/release_config.py`, and import
  them in `bundle.py` (D3). Verify `uv run pytest scripts/tests/workspace/test_bundle.py
  scripts/tests/workspace/test_release_config.py` passes unchanged.
- [ ] 1.2 In `scripts/tests/workspace/test_release_config.py`, write the new tests first and run them against the
  unchanged check, recording that they fail: with both runners added to a copy's group, removing
  `troupe-runner-scripted` (and, separately, `troupe-runner-claude-code`) gives exactly D4's "but troupe-run ships it"
  message; a component that's neither a `packages/*` member nor a bundle dependency (a new `plugins/runner-new`
  member left out of `troupe-run`'s dependencies, put in the group) gives D4's "doesn't ship it" message. Replace
  `test_a_plugin_in_the_linked_group_is_named`, whose refusal no longer holds. Keep
  `test_a_package_left_out_of_the_linked_group_is_named` and the protocol test as they are.
- [ ] 1.3 In `_group_problems`, expect the `packages/*` members plus the workspace members named in the bundle's
  `[project] dependencies`, found by name through `members(root)` with no `packages/troupe-run` literal (D1, D2), and
  give D4's messages. When the bundle isn't a member or has no `pyproject.toml`, expect `packages/*` alone. Update the
  module's docstrings (`LINKED_GROUP`'s says "every packages/* member"). Verify the tests from 1.2 pass and
  `uv run pytest scripts/tests/test_check_paths_reach.py` still passes.
- [ ] 1.4 Add a test that the bundle missing from the workspace adds no group message beyond the `packages/*` ones
  (D2), written to fail if the check raises. Verify it passes.

## 2. The runners join the linked group

- [ ] 2.1 Add `troupe-runner-claude-code` and `troupe-runner-scripted` to the `troupe` linked-versions plugin's
  `components` in `release-please-config.json`. Verify the copy-of-the-real-files tests (both `as-is` and `released`)
  and `test_every_workspace_member_is_configured_for_release` pass, and that the file still validates against the
  `$schema` it names (release-please v17.6.0's `config.json`, checked with `check-jsonschema` or a short
  `jsonschema` run via `uvx`).
- [ ] 2.2 Record in this task how D5's proof reads: the real group holds both runners and the bundle, and a copy
  without a runner fails the check with the message from 1.2.

## 3. Docs

- [ ] 3.1 In `contributing/releasing.md`, "What bumps what": the linked group is core, the adapters, the runners and
  the bundle, because the bundle ships the latest release of everything in it (#214); a runner-only fix releases the
  whole group and makes a `troupe-run-v<version>` tag; runners leave the group when they move to their own
  repositories (#38, #67). Replace the "Each plugin versions on its own" bullet. "Adding a package": a package the
  bundle ships also goes in the group, and the check names one that isn't. Verify by reading both sections against
  `release-please-config.json`, and that `uv run pytest scripts/tests/workspace` (which includes the docs-reference
  tests) passes.
- [ ] 3.2 In `docs/backstage/changelog.md`, change the Plugins section's "Each plugin is released on its own, at its
  own version" to say the runners release with troupe, at its version. Verify the user-docs tests pass (`uv run
  scripts/check.py`).

## 4. Integration

- [ ] 4.1 Run `uv run scripts/check.py` and `openspec validate runners-in-linked-group --strict`, and record both
  results here.

## Workflow follow-up

- Draft pull request closing #215; act on Claude's review; mark ready; archive on the branch; the owner merges.
- After the merge: comment on #215 with the PR and the archived change, check it's closed and its card is Done.
- No Purpose changes, so no `oob/troupe-spec-purposes.json` update in infrastructure.
