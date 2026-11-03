# Tasks

## 1. The check: excluded exactly while a member is bare

- [x] 1.1 Add `bundle_state.add_member(root, name)` to `scripts/tests/bundle_state.py` (D5). In a copy, it adds
  `packages/<name>/pyproject.toml`, a release config entry with its `uv.lock` extra-file, the manifest at `0.0.0`,
  the `uv.lock` package entry, and a bare dependency in the bundle. Update `unpinned`'s docstring: the exclusion goes
  with "something is bare". Verify with a test that a copy with `add_member` and the exclusion has no
  `release_config.problems` or `bundle.problems`.
- [x] 1.2 Write the failing tests first in `scripts/tests/workspace/test_release_config.py`, then run them on this
  branch's unchanged `release_config.py` and show they fail (D2's table):
  - a new member added after the bundle's first release (`pinned`, bundle at 0.1.0, `add_member`, no exclusion) is
    named, with `release-please-config.json`, the line to add, and that it stays until the member is released and
    pinned
  - the same with the exclusion passes
  - two bare members are both named, in one problem
  - with nothing bare, an exclusion is named for removal, with the bundle at 0.0.0 and at 0.1.0
  - with something bare, an exclusion of anything else is named (the existing parametrised test, with the bare state
    built rather than relying on the bundle being at 0.0.0)
  - a malformed pin isn't counted as bare: only `_pin_problems`' message appears

  Rename or replace the bootstrap tests whose names say "before the bundle's first release", so each name says what
  its body checks.
- [x] 1.3 Replace `_bootstrap_problems` in `scripts/release_config.py` with the rule (D2), and update the module's and
  the function's docstrings to cite this change. Verify the 1.2 tests pass, and `uv run pytest
  scripts/tests/workspace/test_release_config.py scripts/tests/workspace/test_bundle.py` passes.
  (Verified after 2.2: the copies' pinned state runs the pinning step, which removed the exclusion
  while the SDK stayed bare until 2.2 changed it.)
- [x] 1.4 Add `"exclude-paths": ["packages/troupe-run"]` to `troupe-run`'s entry in `release-please-config.json`, on
  its own line after `"component"` (D4). Verify `uv run scripts/check.py` passes on the branch, and fails without the
  line, naming `troupe-plugin-sdk`.

## 2. The pinning step keeps the exclusion while anything stays bare

- [x] 2.1 Write the failing tests in `scripts/tests/workspace/test_pin_bundle.py` and show they fail on the unchanged
  `pin_bundle.py`:
  - after `add_member` with the exclusion, moving another component's pin keeps the exclusion byte for byte, and the
    message names the bare member and says `troupe-run` stays out of release pull requests until it's pinned
  - once the manifest gives that member a release, and its `CHANGELOG.md` has the section, the pin removes the
    exclusion, and the message has no such paragraph
  - the result passes `release_config.problems` in both cases

  Update `test_the_first_pin_removes_only_the_bootstrap_exclusion` (and any test that assumes the first pin leaves
  nothing bare) so its copy gives the SDK a release before pinning, and its name says so.
- [x] 2.2 Change `pin_bundle.apply` and `message` (D3), and the module docstring. Verify the 2.1 tests and the rest of
  `test_pin_bundle.py` pass.
- [x] 2.3 In `.github/workflows/release.yml`, replace the pinning pull request description's "Merging it releases
  troupe-run in the next release pull request" with wording true in both cases (the message it quotes says which).
  Verify `scripts/tests/test_release_workflow.py` passes, and update it if it asserts the old line.

## 3. Docs

- [x] 3.1 Update `contributing/releasing.md`. "The bundle's first release" becomes the standing rule: excluded while
  anything is bare, the pinning pull request removes it with the last pin. "Adding a package" adds the exclusion with
  the bare dependency (the check names it), instead of asking for a non-releasing commit type. Verify that
  `grep -n "build(bundle)\|exclude-paths" contributing/releasing.md` shows only the new wording, and that the docs
  tests (`scripts/tests/workspace/test_install_docs.py`, and any docs check in `scripts/check.py`) pass.

## 4. Integration

- [ ] 4.1 Run `uv run scripts/check.py` and show it passing, then confirm the matrix (Linux, macOS and Windows, every
  supported Python) passes on the pull request once it's ready.
- [x] 4.2 Check that no Purpose changed (`git diff main -- openspec/specs` is empty before archive, and the delta has no
  `## Purpose`), so troupe-run/infrastructure's `oob/troupe-spec-purposes.json` needs no pull request.

## Workflow follow-up

- Open a draft pull request that closes #262, act on Claude's review of the last push, then mark it ready.
- Archive the change on the branch before merging. The owner merges.
- After the merge, comment on #262 with the pull request and the archived change, and check its card says Done.
- After the SDK's first release, check that the pinning pull request removes the exclusion and that the next release
  pull request releases `troupe-run` (design, Risks).
