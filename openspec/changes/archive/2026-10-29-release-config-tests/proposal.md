# Proposal

Issue: #188.

## Why

The release pull request (#89) fails `check` on every platform and Python version
([run 40854801952](https://github.com/troupe-run/troupe/actions/runs/40854801952)). Six tests in
`scripts/tests/workspace/test_release_config.py` copy the real repository and expect messages that name the
protocol's manifest version as `0.0.0`. The release pull request bumps `.release-please-manifest.json` (and the
version the troupe package records) to `0.1.0`, so `release_config.problems` correctly names `0.1.0` and the tests
fail. It isn't a flake: every release from now on hits it. The releases spec already requires the release pull
request to pass every required check; the tests are wrong, not the requirement or the check.

A seventh test is wrong in a quieter way: `test_a_record_that_differs_from_the_manifest_names_both_files_and_versions`
writes `0.2.0` as the "different" version, so once the protocol reaches `0.2.0` it stops testing a difference at all.

This blocks merging #89, and so the 0.1.0 tags that #144's install check runs against and the `CHANGELOG.md` links in
troupe-run/website#51.

## What Changes

- **The tests read the protocol's version from the copied manifest** instead of assuming `0.0.0`:
  - `test_a_missing_record_is_named_with_the_manifests_version`
  - `test_a_record_that_doesnt_hold_only_a_version_is_named` (all four cases)
  - `test_a_record_that_differs_from_the_manifest_names_both_files_and_versions`
- **The "differs" case derives a version that can't equal the manifest's** (the next major after it), rather than a
  fixed `0.2.0`.
- **Every test in the file runs on two copies:** the repository as it is, and the repository as a release pull
  request leaves it (every manifest version and the recorded protocol version bumped). This is what would have
  caught #188 before a release did, and it keeps catching the same mistake in tests added later.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None: tests only. The releases spec already requires that the release pull request passes every required check
("The release pull request passes every required check") and that the check names the manifest's protocol version
("A protocol release updates the version troupe records"). `release_config.py` already does that; the change
declares `skip_specs`.

## Impact

- `scripts/tests/workspace/test_release_config.py` only. No production code and no change to `release_config.py`.
- Out of scope, noted for a possible follow-up: `release_config.problems` suggests `"protocol": "0.0.0"` when the
  protocol is missing from the manifest, and `"<path>": "0.0.0"` for a member missing from it. For a new member
  `0.0.0` is right. For the protocol after it has released, it's a weak suggestion (the real fix is restoring the
  released version), but no test fails on it and no release reaches it. These messages and their tests are left as
  they are.
