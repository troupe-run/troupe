# Tasks

## 0. Before any change

- [x] 0.1 Save the release pull request's current diff, `gh pr diff 89 -R troupe-run/troupe`, to the scratchpad, for
  the follow-up's comparison after the merge (design, Migration Plan). Verify the file is non-empty and names
  `0.1.0`.
  - 704 lines, 43 mentions of `0.1.0`, at #89's head `5adefde`. Its changelog headings carry the release date, so
    the comparison ignores date-only differences. The scratchpad is this session's; if it's gone by then, compare
    against #89's commit `5adefde` instead (`gh api repos/troupe-run/troupe/compare/main...5adefde`, or the
    pull request's commit history).

## 1. The check refuses a config without the setting (design D3)

- [x] 1.1 In `scripts/tests/workspace/test_release_config.py`, write the tests first and run them against the
  unchanged check, recording that they fail: a copy without the top-level `prerelease` gives D3's "doesn't set"
  message; a copy with `false`, `"true"` and `1` (parametrised) gives D3's "is {value!r}" message; a copy where
  `packages/troupe`'s entry, and separately the protocol's, sets `prerelease` gives D3's "sets 'prerelease'"
  message. Each asserts the whole message, as the existing tests do.
  - Against the unchanged check, all 16 cases (each × `as-is`/`released`) failed, each getting `[]`.
- [x] 1.2 In `scripts/release_config.py`, add the check to `problems()` with D3's messages, and a constant or
  docstring naming design D3. Verify the tests from 1.1 pass, and that ruff, ruff format and `mypy --strict` are
  clean on both files.
  - The value is named as JSON (`"true"`, `false`, `1`), as it's written in the file, not Python's repr (D3,
    updated). Until 2.1, every test also got the "doesn't set" message from the real config, so 1.1's tests were
    verified after 2.1: `test_release_config.py`, 85 passed; ruff, ruff format and `mypy --strict` clean.

## 2. Releases before 1.0 are pre-releases (design D1)

- [x] 2.1 Add `"prerelease": true` at the top level of `release-please-config.json`, after `bump-minor-pre-major`.
  Verify the copy-of-the-real-files tests (`as-is` and `released`) and
  `test_every_workspace_member_is_configured_for_release` pass, and that the file validates against release-please
  v17.6.0's schema (`uvx check-jsonschema --schemafile <v17.6.0 schemas/config.json> release-please-config.json`).
  Record that, before this task, the real files failed with D3's "doesn't set" message.
  - 2026-11-01: before it, `problems()` on the real files gave exactly ["release-please-config.json doesn't set
    'prerelease': set it to true at the top level, so releases before 1.0 are pre-releases."]. After it,
    `test_release_config.py`, 85 passed (both `as-is` and `released`), and `uvx check-jsonschema --schemafile
    <v17.6.0 config.json> release-please-config.json`: "ok -- validation done".

## 3. Docs (design D2, D4)

- [x] 3.1 In `contributing/releasing.md`: "How a release happens", step 3, says each release below 1.0 is a
  pre-release, that it stops by itself when a component reaches 1.0, and that GitHub shows no Latest release until
  then; "Checking each release's install" says a pre-release starts the check too. Verify by reading both against
  the config and design's Context, and that `uv run pytest scripts/tests/workspace` (which includes the
  docs-reference tests) passes.
  - Read against the config and Context: step 3 names the top-level setting, the 0.x-only rule, the stop at 1.0,
    the check, and that the release pull request doesn't show it. `uv run pytest scripts/tests/workspace`: 182
    passed.
- [x] 3.2 In `docs/backstage/changelog.md`, add that releases before 1.0 show as Pre-release on GitHub. Verify the
  user-docs tests pass (in 4.1's check).
  - One sentence after the opening paragraph, linking it to 1.0's stability promise.

## 4. Integration

- [x] 4.1 Run `uv run scripts/check.py` and `openspec validate prerelease-before-1-0 --strict`, and record both
  results here.
  - 2026-11-01, macOS: `check: all gates passed` (3129 passed, 14 skipped, 110 s); "Change 'prerelease-before-1-0'
    is valid".

## Workflow follow-up

- Draft pull request closing #217; act on Claude's review; mark ready; archive on the branch; the owner merges, before
  #89.
- After the merge: compare #89's regenerated diff with 0.1's copy; it should be unchanged. Comment on #217 with the
  PR, the archived change and that comparison.
- After the owner merges #89 (0.1.0): check each release shows as Pre-release (`gh release list -R
  troupe-run/troupe` shows `Pre-release`, none `Latest`), and that the `release install check` ran against
  `troupe-run-v0.1.0`. Record both on #217. The PR's `Closes #217` closes it at the merge, and its card goes to Done
  then as usual; if either check fails, reopen #217 (its card goes back to In Progress).
- No Purpose changes, so no `oob/troupe-spec-purposes.json` update in infrastructure.
