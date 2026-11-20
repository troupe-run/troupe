# Tasks

## 1. The check (D1, D2)

- [ ] 1.1 Write `scripts/tests/test_release_tags.py` first, against the real config and manifest shapes. Cover:
  every version tagged passes; the 0.2.0 case (troupe-runner-ollama 0.1.0 and protocol 0.2.0 without tags)
  fails, naming both tags and the guide's section; `0.0.0` is skipped; a manifest path with no config entry, an
  entry with no `component`, `include-component-in-tag` not `true`, and a version that isn't `X.Y.Z` each fail,
  naming the input; and the script run as the workflow runs it (refs on stdin) exits 1 and 0. Verify: the tests fail
  with the module missing (`uv run pytest scripts/tests/test_release_tags.py`).
- [ ] 1.2 Write `scripts/release_tags.py` (standard library only, reusing `release_config`'s file names). Verify:
  the tests from 1.1 pass. Running it on this checkout with today's tags
  (`gh api --paginate repos/troupe-run/troupe/git/matching-refs/tags --jq '.[].ref' | python3 scripts/release_tags.py`)
  names exactly `troupe-runner-ollama-v0.1.0` and `protocol-v0.2.0` while they're missing.
- [ ] 1.3 Add the script to `scripts/check-paths.toml`'s `scripts` scope. Verify: `uv run scripts/check.py` passes.

## 2. The release workflow (D3)

- [ ] 2.1 In `scripts/tests/test_release_workflow.py`, test the new `release-tags` job first: `needs: release-please`,
  `if: ${{ !cancelled() }}`, no `environment`, `contents: read` only, checks out `main`, and pipes the tag refs from
  `gh api --paginate .../git/matching-refs/tags` into `scripts/release_tags.py`. Verify: the tests fail before the
  workflow edit.
- [ ] 2.2 Add the job to `.github/workflows/release.yml`, and update the workflow's header comment. Verify: the
  tests from 2.1 pass, and `actionlint` (if installed) or the guard's workflow checks pass on the file.

## 3. The repair route (D4)

- [ ] 3.1 Add "Repairing a missing release" to `contributing/releasing.md`: what the check's failure means, route 1
  (edit the merged release PR's body, the double escaping, relabel, re-run) and route 2 (`gh release create`).
  Link it from "When something goes wrong". Verify: the anchor the script prints matches the rendered heading
  (`#repairing-a-missing-release`), and the docs check in `uv run scripts/check.py` passes.

## 4. Finish

- [ ] 4.1 Mutation checks: remove a tag from the stdin list in a test run, or point the script at a manifest
  with a bumped version. Each must fail the check with that tag named. Revert.
- [ ] 4.2 `uv run scripts/check.py` passes in full. Verify: its output, kept in a scratch file.

## Workflow follow-up

- The merge waits for #263's retrigger (troupe-runner-ollama-v0.1.0 and protocol-v0.2.0 exist), so this change's merge
  run passes.
- After the merge: confirm the merge run's `release-tags` job passed, then comment on #484 with the PR and the
  archived change.
