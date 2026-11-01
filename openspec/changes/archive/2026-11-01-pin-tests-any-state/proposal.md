# Proposal

Issue: #229.

## Why

The first pinning pull request, #228 (`feat(bundle)!: ship 9 component releases`), fails `check` on every Ubuntu leg.
Eleven tests in `scripts/tests/workspace/` copy the real repository and edit or read it as if the bundle were still
unpinned: they look for bare dependency lines (`"troupe-runner-scripted",`) and for `troupe-run`'s bootstrap
`exclude-paths`. #228 is the commit that pins every dependency and removes that key, so those lines no longer exist.
Reproduced locally on #228's head (`afde24d`): 11 failed, 155 passed; the same three files pass on `main` (399a9e7).

It's the same kind of bug as #188 (tests that assumed the manifest's version), and it isn't a one-off: every state
after the first pin is pinned, so the tests fail on #228 and on `main` for good once it merges. Two more tests in
`test_pin_bundle.py` pass on #228 only because nothing moves there: they check the first pin against a copy that's
already pinned, so they check nothing.

This blocks merging #228, and so the bundle's 0.1.0 (`troupe-run-v0.1.0`) and its install check.

## What Changes

- **A shared test helper builds the bundle's state in a copy**, rather than relying on the repository's:
  - *unpinned*, as before the first pin: every dependency on a member bare, the bootstrap `exclude-paths` present,
    and the bundle unreleased in the manifest;
  - *pinned*, as the pinning step leaves it: every released member pinned at its manifest version, the exclusion gone.
- **`test_bundle.py` and `test_release_config.py` run every case on both states**, so a test that assumes either one
  fails in the ordinary check on `main`, not first on a pinning pull request. `test_release_config.py` already runs
  on the repository as-is and as a release leaves it (#188); each of those now runs unpinned and pinned.
- **`test_bundle.py`'s edits find a dependency by its name**, whatever its form, instead of matching a bare line.
- **`test_pin_bundle.py`'s copy is built unpinned**, as its docstring already says (the state merging the first
  release pull request leaves), so its first-pin cases test a first pin wherever they run.
- **The first-pin tests assert that something moved**, so a copy that's already pinned fails them rather than
  passing vacuously.
- **The missing-manifest test builds the state its message is about**: a member missing from the manifest is named
  bare, as a new member would be.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None: tests only. The releases spec already requires that the bundle names each member bare or pinned ("The bundle
pins each component at a release tag"), that the first pinning pull request removes the bootstrap exclusion ("The
bundle's first release follows its components'"), and that release and pinning pull requests pass every required
check. `bundle.py`, `pin_bundle.py` and `release_config.py` already do what the spec says; only the tests assume one
state. The change declares `skip_specs`, as #188's did.

## Impact

- `scripts/tests/workspace/test_bundle.py`, `test_pin_bundle.py`, `test_release_config.py`, and a new shared helper
  module beside them. No production code changes.
- The three files' case count roughly doubles for `test_bundle.py` and `test_release_config.py` (each case runs on
  both states). They are file-copy tests of a few tens of milliseconds each.
- Once merged, #228's CI is re-run: its `pull_request` run checks out the pull request merged into the latest `main`,
  so it picks up the fixed tests without regenerating #228.
- Out of scope: with the bundle pinned, a member missing from the manifest also gets the check's "pins … but the
  manifest gives 0.0.0" message, which suggests naming it bare rather than restoring the manifest entry. Two
  inconsistent files giving two messages is defensible, and no real state reaches it (a pinned member has released,
  so it's in the manifest). Left as it is; noted in the design.
