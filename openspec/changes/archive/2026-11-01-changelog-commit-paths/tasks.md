# Tasks

## 0. Before any change

- [x] 0.1 Save the release pull request's current diff (`gh pr diff 89 -R troupe-run/troupe`) to the scratchpad for
  the follow-up's comparison, and record #89's head commit here. Verify the file is non-empty and that troupe's
  changelog in it doesn't list `74cbf20` and does have a Documentation section (the two symptoms this change
  removes).
  - 2026-11-01: #89's head `cd20f75` (built from `e18bb96`), 688 lines. `74cbf20` appears 0 times; troupe's
    changelog has a Documentation section. The manual check in #89's comment reports one stray, `7e03119` in
    troupe's. The scratchpad is this session's; if it's gone, compare against #89's commit `cd20f75`.

## 1. The check holds the three settings (design D4)

- [x] 1.1 In `scripts/tests/workspace/test_release_config.py`, write the tests first and run them against the
  unchanged check, recording that they fail: for each of `commit-batch-size` and `commit-search-depth`, a copy
  without it gives D4's "doesn't set" message, and a copy with another value (parametrised: a smaller number, the
  string form, and for the depth 500) gives D4's "is {value}" message; a copy without `changelog-sections` gives
  the "doesn't set" message, and copies where `docs` is shown, a section is missing, and the list is reordered give
  the "is {value}" message; a copy where `packages/troupe`'s entry, and separately the protocol's, sets
  `changelog-sections` gives the "sets 'changelog-sections'" message. Each asserts the whole message, as the
  existing tests do.
  - The values are written out in the test (`SECTIONS`, `HISTORY`), not imported from the check, so a change to
    the check's copy fails a test. A float (`100.0`) is also another value. Against the unchanged check, all 28
    cases (each × `as-is`/`released`) failed, each getting `[]`.
- [x] 1.2 In `scripts/release_config.py`, add `COMMIT_BATCH_SIZE`, `COMMIT_SEARCH_DEPTH` and `CHANGELOG_SECTIONS`
  with docstrings citing design D1 to D3 and #223, and `_history_problems` called from `problems()`, with D4's
  messages. Verify the tests from 1.1 pass once 2.1 is in, and that ruff, ruff format and `mypy --strict` are clean
  on both files.
  - Each message also says why the value matters (`HISTORY_SETTINGS`), and the comparison is as JSON, so
    `"100"` and `100.0` aren't taken as 100. After 2.1: `test_release_config.py`, 113 passed; ruff, ruff format
    and `mypy --strict` clean on both files.

## 2. The settings (design D1 to D3)

- [x] 2.1 Add `"commit-batch-size": 100`, `"commit-search-depth": 1000` and D3's `changelog-sections` at the top of
  `release-please-config.json`, after `prerelease`. Record that, before this task, `problems()` on the real files
  gave exactly D4's three "doesn't set" messages. Verify the copy-of-the-real-files tests (`as-is` and `released`)
  pass, and that the file validates against release-please v17.6.0's schema
  (`uvx check-jsonschema --schemafile <v17.6.0 schemas/config.json> release-please-config.json`).
  - 2026-11-01: before it, `problems()` on the real files gave exactly D4's three "doesn't set" messages
    (`commit-batch-size`, `commit-search-depth`, `changelog-sections`). After it, `test_release_config.py`, 113
    passed (both `as-is` and `released`), and `uvx check-jsonschema` against v17.6.0's `schemas/config.json`
    (from the npm package): "ok -- validation done".

## 3. Docs, and the release pull request as release-please would build it

- [x] 3.1 In `contributing/releasing.md`, make design D5's edits ("What bumps what", and a new "How commits reach
  changelogs" section pointing at #223); in `docs/backstage/changelog.md`, name the sections a reader sees. Verify
  by reading each against the config and design's Context, and that `uv run pytest scripts/tests/workspace` (which
  includes the docs-reference tests) passes.
  - Read against the config and Context: "What bumps what" says the sections do it and that hidden breaking
    changes still list and release; the new section names both settings, the page-boundary case, its limit, #223
    and the manual check on #89; "When something goes wrong" says what to do about a stray entry.
    `uv run pytest scripts/tests/workspace`: 210 passed; the user-docs tests (`test_user_docs_*`): 86 passed.
- [x] 3.2 After the branch is pushed, ask the owner to dry-run release-please against it, since it needs their
  token: `! npx release-please@17.6.0 release-pr --dry-run --token "$(gh auth token)" --repo-url
  troupe-run/troupe --target-branch changelog-commit-paths --config-file release-please-config.json
  --manifest-file .release-please-manifest.json`. Verify from its output that troupe's changelog lists `74cbf20`,
  that no changelog has a Documentation section, that `69d6c27` is only in troupe's, runner-scripted's and the
  protocol's, and that `dd6189b` is only in troupe's; record the result here. If the owner prefers not to, record
  that, and the follow-up's check of #89 is the proof.
  - 2026-11-01, the owner ran it against `e1365cd` (exit 0). It read the config from the branch ("commit search
    depth: 1000"), fetched history in pages of 100, and considered all 577 commits. Its release pull request
    body: 11 components, all at 0.1.0; no Documentation section; `74cbf20` in troupe's changelog; `69d6c27` only
    in protocol's, troupe's and runner-scripted's; `dd6189b` only in troupe's; `7e03119` in none. Each of the 196
    entries' commits was checked with `git show` against its component's directory: 0 stray.

## 4. Integration

- [x] 4.1 Run `uv run scripts/check.py` and `openspec validate changelog-commit-paths --strict`, and record both
  results here.
  - 2026-11-01, macOS, at `e1365cd`'s commit: `check: all gates passed` (3157 passed, 14 skipped, 128 s); "Change
    'changelog-commit-paths' is valid".

## 5. A race the merge queue found (#226, after archiving)

- [x] 5.1 The merge queue dropped #225 twice: `test_a_slow_example_passes_under_the_profile_the_flake_hunt_asks_for`
  failed on Windows legs (1 of 4, then 2 of 4), each with `FileNotFoundError` on a
  `Temp\troupe-claude-code-*` directory, the Claude Code runner tests' private directory. The owner asked for it to
  be fixed here, since these changes started showing it. Cause, read in pytest 9.1.1's `Session.collect`: a path
  argument's parents are collected down from the root, stopping at the first one above `confcutdir` (the
  repository). On CI the repository is on `D:` and the temp directory on `C:`, so none is, and the child collected
  `C:\` down to the test; on Windows each entry that doesn't match is compared with `samefile_nofollow`, which
  stats it, so a sibling removed between listing and stat fails collection. The fix passes `--confcutdir
  <tmp_path>` in `run_slow`, and `test_the_slow_examples_run_collects_no_directory_outside_its_own` records every
  `Dir` the child collects (a `-p` plugin) and requires them all inside `tmp_path`. Verify the new test fails
  without the flag and passes with it, and that the file is ruff, ruff format and `mypy --strict` clean.
  - 2026-11-01, macOS: without the flag the new test failed, the child having collected the temp directory and
    its parents (the walk happens on every platform; only Windows stats the siblings). With it, the file's 5
    tests passed, in 5.6 s rather than 44.8 s. ruff, ruff format and `mypy --strict` clean. The only other child
    pytest command in the repository, `scripts/tests/test_on.py`, records arguments and runs nothing.

## Workflow follow-up

- Draft pull request closing #222 and mentioning #223 (which it doesn't close); act on Claude's review; mark ready;
  archive on the branch; the owner merges, before #89.
- After the merge: compare #89's regenerated diff with 0.1's copy. Every shown entry is under only the components
  its commit changed, `74cbf20` and the other oldest commits are in, no Documentation section is left, and every
  version is still 0.1.0. Comment on #222 with the PR, the archived change and that comparison.
- Before the owner merges #89, run the manual check in #89's comment
  (https://github.com/troupe-run/troupe/pull/89#issuecomment-6552218406) on the build being merged. A failing
  release-pull-request check was considered and left for later (owner, 2026-11-01).
- Then on the next push to `main` that changes no component, check #89's changelogs didn't change. If they did,
  or a stray entry shows up, that's #223's revisit trigger: comment there before #89 merges.
- On #223: comment with the PR and that option A is in place, and close it as decided (owner, 2026-11-01), unless
  the owner wants it left open to revisit.
- No Purpose changes, so no `oob/troupe-spec-purposes.json` update in infrastructure.
