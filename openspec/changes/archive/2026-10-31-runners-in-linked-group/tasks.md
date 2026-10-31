# Tasks

## 1. The check takes the group from what the bundle ships (design D1–D4)

- [x] 1.1 Move `normalise` and `requirement_name` from `scripts/bundle.py` to `scripts/release_config.py`, and import
  them in `bundle.py` (D3). Verify `uv run pytest scripts/tests/workspace/test_bundle.py
  scripts/tests/workspace/test_release_config.py` passes unchanged.
  - 71 passed, unchanged. mypy later refused `test_bundle.py` reading `bundle.requirement_name` (no longer
    exported there), so that one assertion now reads it from `release_config`.
- [x] 1.2 In `scripts/tests/workspace/test_release_config.py`, write the new tests first and run them against the
  unchanged check, recording that they fail: removing `troupe-runner-scripted` (and, separately,
  `troupe-runner-claude-code`) from a copy's group gives exactly D4's "but troupe-run ships it" message; a runner
  dropped from `troupe-run`'s dependencies but kept in the group (the move-out case, D1) gives D4's "doesn't ship it"
  message; a component that isn't a workspace member gives D4's "isn't a workspace member" message. Replace
  `test_a_plugin_in_the_linked_group_is_named`, whose refusal no longer holds. Keep
  `test_a_package_left_out_of_the_linked_group_is_named` and the protocol test as they are.
  - Against the unchanged check, all eight cases (each × `as-is`/`released`) failed: the left-out runners gave `[]`,
    the other two the old "only packages/* members belong there" message.
- [x] 1.3 In `_group_problems`, expect the `packages/*` members plus the workspace members named in the bundle's
  `[project] dependencies`, found by name through `members(root)` with no `packages/troupe-run` literal (D1, D2), and
  give D4's messages. When the bundle isn't a member or has no `pyproject.toml`, expect `packages/*` alone. Update the
  module's docstrings (`LINKED_GROUP`'s says "every packages/* member"). Verify the tests from 1.2 pass and
  `uv run pytest scripts/tests/test_check_paths_reach.py` still passes.
  - With 2.1's config: `test_release_config.py`, `test_bundle.py` and `test_check_paths_reach.py`, 123 passed; ruff,
    ruff format and `mypy --strict` clean.
- [x] 1.4 Add a test that the bundle missing from the workspace adds no group message beyond the `packages/*` ones
  (D2), written to fail if the check raises. Verify it passes.
  - `test_without_the_bundle_the_group_is_checked_against_packages_alone` asserts the whole list. Its first run
    showed the check saying "troupe-run doesn't ship" troupe-run and each runner, so the refusal was split (D4,
    updated) before it passed.

## 2. The runners join the linked group

- [x] 2.1 Add `troupe-runner-claude-code` and `troupe-runner-scripted` to the `troupe` linked-versions plugin's
  `components` in `release-please-config.json`. Verify the copy-of-the-real-files tests (both `as-is` and `released`)
  and `test_every_workspace_member_is_configured_for_release` pass, and that the file still validates against the
  `$schema` it names (release-please v17.6.0's `config.json`, checked with `check-jsonschema` or a short
  `jsonschema` run via `uvx`).
  - 2026-10-31: `uvx check-jsonschema --schemafile <v17.6.0 config.json> release-please-config.json`: "ok --
    validation done". `test_release_config.py`, 69 passed, both `as-is` and `released`.
- [x] 2.2 Record in this task how D5's proof reads: the real group holds both runners and the bundle, and a copy
  without a runner fails the check with the message from 1.2.
  - Before 2.1, the new check on the real files gave exactly: "troupe-runner-claude-code isn't in the 'troupe'
    linked group in release-please-config.json, but troupe-run ships it: add it to its 'components'." and the same
    for troupe-runner-scripted. After it, `test_every_workspace_member_is_configured_for_release` passes, and the
    group holds core, the six adapters, both runners and `troupe-run`, so release-please's linked-versions plugin
    releases them together on a runner-only `fix:`.

## 3. Docs

- [x] 3.1 In `contributing/releasing.md`, "What bumps what": the linked group is core, the adapters, the runners and
  the bundle, because the bundle ships the latest release of everything in it (#214); a runner-only fix releases the
  whole group and makes a `troupe-run-v<version>` tag; runners leave the group when they move to their own
  repositories (#38, #67). Replace the "Each plugin versions on its own" bullet. "Adding a package": a package the
  bundle ships also goes in the group, and the check names one that isn't. Verify by reading both sections against
  `release-please-config.json`, and that `uv run pytest scripts/tests/workspace` (which includes the docs-reference
  tests) passes.
  - Read against the config: the group's ten components match the new bullet. `uv run pytest scripts/tests/workspace`:
    166 passed.
- [x] 3.2 In `docs/backstage/changelog.md`, change the Plugins section's "Each plugin is released on its own, at its
  own version" to say the runners release with troupe, at its version. Verify the user-docs tests pass (`uv run
  scripts/check.py`).
  - Also reworded the "troupe" section's opening, which said only core and the adapters release together. The
    user-docs tests run in 4.1's check.

## 4. Integration

- [x] 4.1 Run `uv run scripts/check.py` and `openspec validate runners-in-linked-group --strict`, and record both
  results here.
  - 2026-10-31, macOS: `check: all gates passed` (3104 passed, 14 skipped, 123 s); "Change 'runners-in-linked-group'
    is valid".

## Workflow follow-up

- Draft pull request closing #215; act on Claude's review; mark ready; archive on the branch; the owner merges.
- After the merge: comment on #215 with the PR and the archived change, check it's closed and its card is Done.
- No Purpose changes, so no `oob/troupe-spec-purposes.json` update in infrastructure.
