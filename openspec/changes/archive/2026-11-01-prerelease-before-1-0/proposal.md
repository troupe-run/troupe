# Proposal

## Why

1.0 holds troupe's stability promise, so a 0.x release should say it's one on GitHub (owner, 2026-11-01, before
merging the 0.1.0 release pull request, #89). Today release-please creates every GitHub release as a full release, and
GitHub gives the "Latest" badge to whichever of the 11 components it created last. Marking 0.x releases as
pre-releases fixes both: GitHub shows no "Latest" badge until 1.0. This change is #217, and it has to land before #89
merges for 0.1.0's releases to be pre-releases.

## What Changes

- **Releases before 1.0 are pre-releases.** `release-please-config.json` sets release-please's `prerelease` option
  once, at the top level, so every component inherits it. release-please applies it only to a version whose major is
  0 (or that carries a semver pre-release suffix), so it stops by itself when a component reaches 1.0. It's read when
  release-please creates the GitHub releases, so the release pull request doesn't change.
- **The check keeps it set.** `scripts/release_config.py` fails when the top-level `prerelease` isn't `true`, or when
  a package entry sets `prerelease` itself, naming the file and the fix.
- **The docs say so.** `contributing/releasing.md` says releases are pre-releases until 1.0, that this stops by
  itself, and that the install check still runs for them. `docs/backstage/changelog.md` says a 0.x release shows as
  Pre-release on GitHub.

Not in this change: anything about 1.0 itself, or how its stability promise is defined.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `releases`: a GitHub release for a version below 1.0 is created as a pre-release; the release-configuration check
  fails when the setting is missing or overridden per package.

## Impact

- `release-please-config.json`: one top-level key, `"prerelease": true`.
- `scripts/release_config.py`: a new problem for a missing, non-`true` or per-package `prerelease`.
- `scripts/tests/workspace/test_release_config.py`: tests for each of those; the copy-of-the-real-files tests cover
  the real config having it.
- `contributing/releasing.md`, `docs/backstage/changelog.md`.
- `.github/workflows/release-install-check.yml` unchanged: it's triggered by `release: published`, which a pre-release
  fires too.
- No runtime code. Nothing has been released yet, so no existing release changes.
