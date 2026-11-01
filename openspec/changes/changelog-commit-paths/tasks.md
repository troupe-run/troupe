# Tasks

## 0. Before any change

- [ ] 0.1 Save the release pull request's current diff (`gh pr diff 89 -R troupe-run/troupe`) to the scratchpad for
  the follow-up's comparison, and record #89's head commit here. Verify the file is non-empty and that troupe's
  changelog in it doesn't list `74cbf20` and does have a Documentation section (the two symptoms this change
  removes).

## 1. The check holds the three settings (design D4)

- [ ] 1.1 In `scripts/tests/workspace/test_release_config.py`, write the tests first and run them against the
  unchanged check, recording that they fail: for each of `commit-batch-size` and `commit-search-depth`, a copy
  without it gives D4's "doesn't set" message, and a copy with another value (parametrised: a smaller number, the
  string form, and for the depth 500) gives D4's "is {value}" message; a copy without `changelog-sections` gives
  the "doesn't set" message, and copies where `docs` is shown, a section is missing, and the list is reordered give
  the "is {value}" message; a copy where `packages/troupe`'s entry, and separately the protocol's, sets
  `changelog-sections` gives the "sets 'changelog-sections'" message. Each asserts the whole message, as the
  existing tests do.
- [ ] 1.2 In `scripts/release_config.py`, add `COMMIT_BATCH_SIZE`, `COMMIT_SEARCH_DEPTH` and `CHANGELOG_SECTIONS`
  with docstrings citing design D1 to D3 and #223, and `_history_problems` called from `problems()`, with D4's
  messages. Verify the tests from 1.1 pass once 2.1 is in, and that ruff, ruff format and `mypy --strict` are clean
  on both files.

## 2. The settings (design D1 to D3)

- [ ] 2.1 Add `"commit-batch-size": 100`, `"commit-search-depth": 1000` and D3's `changelog-sections` at the top of
  `release-please-config.json`, after `prerelease`. Record that, before this task, `problems()` on the real files
  gave exactly D4's three "doesn't set" messages. Verify the copy-of-the-real-files tests (`as-is` and `released`)
  pass, and that the file validates against release-please v17.6.0's schema
  (`uvx check-jsonschema --schemafile <v17.6.0 schemas/config.json> release-please-config.json`).

## 3. Docs, and the release pull request as release-please would build it

- [ ] 3.1 In `contributing/releasing.md`, make design D5's edits ("What bumps what", and a new "How commits reach
  changelogs" section pointing at #223); in `docs/backstage/changelog.md`, name the sections a reader sees. Verify
  by reading each against the config and design's Context, and that `uv run pytest scripts/tests/workspace` (which
  includes the docs-reference tests) passes.
- [ ] 3.2 After the branch is pushed, ask the owner to dry-run release-please against it, since it needs their
  token: `! npx release-please@17.6.0 release-pr --dry-run --token "$(gh auth token)" --repo-url
  troupe-run/troupe --target-branch changelog-commit-paths --config-file release-please-config.json
  --manifest-file .release-please-manifest.json`. Verify from its output that troupe's changelog lists `74cbf20`,
  that no changelog has a Documentation section, that `69d6c27` is only in troupe's, runner-scripted's and the
  protocol's, and that `dd6189b` is only in troupe's; record the result here. If the owner prefers not to, record
  that, and the follow-up's check of #89 is the proof.

## 4. Integration

- [ ] 4.1 Run `uv run scripts/check.py` and `openspec validate changelog-commit-paths --strict`, and record both
  results here.

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
