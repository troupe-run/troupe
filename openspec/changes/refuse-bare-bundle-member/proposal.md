# Proposal: the bundle doesn't release while it names a member bare

Issue: troupe-run/troupe#262. Raised while implementing #240 (change `runner-sdk`, design D12).

## Why

A release pull request can release `troupe-run` while its `pyproject.toml` still names a workspace member bare.
Installing that tag the documented way (`uv tool install --no-sources ...`) then looks the member up on a package index,
where it isn't (so the install fails) or where someone else has registered the name (so the install brings their
package). Nothing stops this before the tag is out: the pinning step pins a member only once it has released, and the
install check on published tags only opens a Bug afterwards.

The window is open on `main` now. `troupe-plugin-sdk` is bare until its first release is pinned, and `troupe-run` has
released, so any releasable commit that touches `packages/troupe-run/` would release a bundle that names the SDK bare.
Only a convention keeps it shut: runner-sdk's commits there use the non-releasing `build` type. The same window opens
whenever a member is added after the bundle's first release.

## What Changes

- **The bundle's release exclusion is tied to its bare members.** `troupe-run`'s entry in `release-please-config.json`
  has `"exclude-paths": ["packages/troupe-run"]` exactly while the bundle names any workspace member bare. While it
  does, release-please keeps the bundle's commits out of release pull requests, so no release pull request can release
  `troupe-run`. This widens the one-off exclusion before the bundle's first release (release-each-package design D7)
  into a standing rule.
- **The check refuses a mismatch.** `scripts/check.py` fails when the bundle names a member bare and the exclusion is
  missing, naming each bare member, the config file and the fix: exclude the bundle's commits until the member has
  released and the pinning pull request pins it. It also fails when the exclusion is set and nothing is bare (as it does
  today once the bundle has released), so the bundle's commits aren't kept out for good. The check no longer depends on
  whether the bundle itself has released.
- **The pinning step removes the exclusion only when nothing is left bare.** `scripts/pin_bundle.py` keeps the
  exclusion when a member stays bare after its moves (a member that hasn't released yet), and says so in the pinning
  commit's message. The pull request's description no longer claims that merging it always releases the bundle.
- **`main` gets the exclusion now**, because the SDK is bare. The commit that adds it releases nothing.
- **The documented convention goes.** `contributing/releasing.md` no longer asks for a non-releasing commit type when
  adding a member to the bundle. It says to add the exclusion with it, which the check enforces.
- **A test shows it for a new member added after the bundle's first release**: the check names it until the exclusion
  is added, and the pinning step keeps the exclusion until that member is released and pinned.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `releases`: "The bundle's first release follows its components'" becomes a rule for every release. The bundle's
  commits are kept out of release pull requests exactly while it names a member bare, the check refuses either
  mismatch, and the pinning pull request removes the exclusion only when it pins the last bare member. "A component
  release is followed by a pinning pull request" gains a scenario for a pin that leaves a member bare.

## Impact

- `scripts/release_config.py`: the bootstrap check becomes the bare-member rule.
- `scripts/pin_bundle.py`: removes the exclusion only when nothing stays bare, and says so in its message when it keeps it.
- `.github/workflows/release.yml`: the pinning pull request's description.
- `release-please-config.json`: `troupe-run` gets the exclusion while the SDK is bare.
- `scripts/tests/bundle_state.py`, `scripts/tests/workspace/test_release_config.py`,
  `scripts/tests/workspace/test_pin_bundle.py`: the fixtures and tests for the rule, including a new member.
- `contributing/releasing.md`: the bundle's first release and adding a package.
- No Purpose changes, so troupe-run/infrastructure's `oob/troupe-spec-purposes.json` is untouched.
