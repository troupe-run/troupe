# Proposal

Issue: #197.

## Why

When a workspace member or the protocol is missing from `.release-please-manifest.json`, `release_config.problems`
tells you to add it at `0.0.0` (`scripts/release_config.py:66` and `:132`). That's right only for something that has
never been released. Once the release pull request (#89) merges and everything is at `0.1.0`, an entry lost from the
manifest (a bad hand edit, or a merge conflict resolved wrongly) gets a fix that moves its version backwards: the
manifest is release-please's record of each component's last release, so it would work from `0.0.0` while the
`<component>-v0.1.0` tag exists. The check is guessing a version it can't know, against the project's "refuse rather
than guess" rule.

Nothing hits this today, and #89 hasn't merged, so there are no tags yet. It's worth fixing before the first release
makes the guess wrong.

## What Changes

- **The two "has no version in the manifest" messages stop suggesting `0.0.0`.** Each says to add the entry with the
  version the component last released, its latest `<component>-v*` tag, names the command that lists those tags on
  `origin`, and says `0.0.0` is right only when there is no such tag. The component is the member's project name
  (which the check already requires to be its `component`) or `protocol`.
- **The check still runs offline and uses the standard library only.** It names where to find the version; it doesn't
  read tags itself (design D1, which settles the open question in #197).
- **Tests:** `test_a_member_missing_from_the_manifest_is_named_with_the_manifest_file`,
  `test_the_protocol_missing_from_the_manifest_is_named` and the manifest line in
  `test_a_new_package_without_release_config_is_named` expect the new messages, under both the `as-is` and `released`
  copies.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `releases`: "Every workspace member is configured for release" says what the check names when a member or the
  protocol is missing from the manifest: restore the version it last released, and `0.0.0` only if it has none.

## Impact

- `scripts/release_config.py` (two messages, plus a helper that builds both) and
  `scripts/tests/workspace/test_release_config.py`.
- No change to release-please's config, the manifest, or any package. No new dependency.
- The check doesn't verify that a restored version is the right one (a manifest entry set back to `0.0.0` after a
  release still passes). Checking versions against tags would need the tags present, which a clone may not have;
  that's out of scope here (design, "Non-Goals").
