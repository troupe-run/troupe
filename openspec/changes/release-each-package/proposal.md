# Proposal

## Why

Core, the six adapters, both runners and the bundle `troupe-run` form one linked group, so a fix to the git port
releases all ten packages at once. #218 decided (owner, 2026-11-01) that **every package versions and releases on its
own, and the bundle is released after them, pinning each shipped component's release tag**. That way any component
release is still followed by a new bundle (#214's rule), and the bundle's version shows the size of the change. It is
built before 0.1.0: release pull request #89 waits for it. This change is #219.

## What Changes

- **No linked group.** `release-please-config.json` loses its `linked-versions` plugin. Core, each adapter, each
  runner, the bundle and the protocol each release only on their own releasable commits, at their own version. One
  combined release pull request is kept (`separate-pull-requests` stays off).
- **The bundle pins what it ships.** Each component in `packages/troupe-run/pyproject.toml`'s dependencies becomes a
  direct reference to its release tag (`troupe-vcs-git @ git+https://github.com/troupe-run/troupe@troupe-vcs-git-v0.1.0#subdirectory=packages/troupe-vcs-git`).
  The root's workspace sources still win locally, so `uv sync`, `uv lock` and every test keep using the workspace's
  own packages, and moving a pin leaves `uv.lock` unchanged (seen with uv 0.13.6; checked again on a probe
  repository).
- **The pinning pull request.** After release-please publishes releases, a new step in the `release` workflow moves
  every pin that's behind its component's latest release. It commits as the release App on a `release-please--`
  branch, and opens (or updates) one pull request. The commit's type is the largest change among the moved pins,
  read from the components' changelogs: breaking, `feat`, otherwise `fix`. The owner merges it through the queue, and
  the next release pull request then releases `troupe-run` at that size.
- **BREAKING (for anyone installing a tag): the tagged install adds `--no-sources`.** Without it, uv applies the
  checkout's workspace sources and installs every component from the bundle's own commit, ignoring the pins. The
  documented command for a `troupe-run-v<version>` tag becomes
  `uv tool install --no-sources "git+…@troupe-run-v<version>#subdirectory=packages/troupe-run"`. Installing `main` or a
  commit keeps today's form, which installs everything from that commit. No tag has been published yet, so nobody's
  install changes (owner, 2026-11-01).
- **The install check follows.** For a bundle tag it runs the `--no-sources` form, and expects `troupe --version` to
  print the version core is pinned at, not the bundle's. Before installing, it refuses a tag whose bundle has a
  component that isn't pinned.
- **The bundle's 0.1.0 comes second.** Every package has releasable history and no tag, so #89 would release
  `troupe-run` with the components. A one-time bootstrap keeps the bundle's history out of #89, and the first pinning
  pull request removes it, so that pull request's commit releases `troupe-run` at 0.1.0 (owner, 2026-11-01: address
  it in this change).
- **Checks.** `scripts/release_config.py` refuses any linked group, a malformed pin, a pin for something that isn't a
  workspace member, and a pin ahead of the manifest. It also refuses the bootstrap once the bundle has released.
  `scripts/bundle.py` reads pinned dependencies by name, as now.
- **Docs.** `contributing/releasing.md` ("What bumps what", "Checking each release's install", "Adding a package",
  and a new section on the pinning pull request) and `docs/backstage/changelog.md` describe the two steps.

Not in this change: pinning each component's commit SHA as well (#220); switching the documented install to the
0.1.0 tag (#208, which now uses the `--no-sources` form); marking 0.x releases as pre-releases (#217).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `releases`: each package versions on its own instead of in one linked group; the bundle follows each component
  release through a pinning pull request whose commit type is the largest change it pins; the release-configuration
  check covers pins and the first-release bootstrap instead of the group.
- `installation`: a tagged install installs each component from its pinned tag (`--no-sources`), while a commit
  install still installs everything from that commit; the install check expects core's pinned version for a tag,
  and refuses an unpinned bundle tag.

## Impact

- `release-please-config.json` (no plugin; the bundle's bootstrap entry), `packages/troupe-run/pyproject.toml`
  (pins, written by the first pinning pull request).
- `.github/workflows/release.yml`: a `pin-bundle` job after `release-please`, with the release App's token.
- New `scripts/pin_bundle.py` and its tests; `scripts/release_config.py`, `scripts/install_check.py`,
  `scripts/bundle.py` (if pinned requirements need it), and their tests under `scripts/tests/workspace/`.
- `README.md` and `docs/opening-night/install.md` only if the docs check's accepted forms change their text; they say
  `@main` until #208.
- `contributing/releasing.md`, `docs/backstage/changelog.md`.
- A probe repository (`infra-probe-*`, private, deleted afterwards) for uv's behaviour, the bootstrap, and the pinning
  pull request end to end.
- No runtime code. No Purpose changes, so no `oob/troupe-spec-purposes.json` update in infrastructure.
