# Proposal

## Why

People install troupe from the bundle's tag, `troupe-run-v<version>` (#189, #212). The bundle depends on both runner
plugins, but they version on their own, outside the linked `troupe` group, so a release that fixes only a runner tags
`troupe-runner-<name>-v<version>` and makes no bundle tag. Until core or an adapter next releases, the fix doesn't
reach anyone who installs by tag. #214 decided it (owner, 2026-10-31): **the bundle ships the latest release of
everything in it**, so any release of a bundled package makes a new bundle, and the runners join the linked group
until they move to their own repositories (#38, #67). This change builds that: #215.

## What Changes

- **The runners join the linked group.** `troupe-runner-scripted` and `troupe-runner-claude-code` go into
  `release-please-config.json`'s `troupe` linked-versions group, with core, the adapters and the bundle. A releasable
  commit to any of them releases all of them at one version, so a runner-only `fix:` makes a `troupe-run-v<version>`
  tag. Nothing has released yet (every manifest version is 0.0.0, and origin has no tags), so no version moves.
- **The group is checked against what the bundle ships.** `scripts/release_config.py` takes the group's expected
  members from the bundle's own dependencies (with the bundle and every `packages/*` member), not from the
  `packages/*` directory alone. A package `troupe-run` depends on that isn't in the group fails the check, naming the
  package, that the bundle ships it, and the fix. A plugin in the group is no longer refused: what's refused is a
  component the bundle doesn't ship.
- **Each runner no longer has its own version.** The `releases` requirement that each plugin versions on its own is
  removed. When #38 or #67 moves a runner to its own repository, it leaves the bundle's dependencies, and the check
  then requires it out of the group, as part of that change.
- **The docs say so.** `contributing/releasing.md` ("What bumps what", "Adding a package") says the bundle ships the
  latest release of everything in it, that a bundled package joins the group, and that runners leave it when they move
  out (#38, #67). `docs/backstage/changelog.md` stops saying each plugin releases on its own.

Not in this change: how dependency updates release (`fix(deps)` for security updates), which is
troupe-run/infrastructure#240.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `releases`: the linked group is the bundle and everything it ships, not only `packages/*`; plugins stop versioning
  on their own; the release-configuration check fails on a bundled package outside the group.

## Impact

- `release-please-config.json`: two components added to the `troupe` linked-versions plugin.
- `scripts/release_config.py`: the group's expected members come from `packages/troupe-run/pyproject.toml`'s
  dependencies as well as `packages/*`; new failure message for a bundled package outside the group; the "only
  `packages/*` members belong there" message changes to name what the bundle ships. `scripts/bundle.py` imports the
  requirement-name helpers it now shares.
- `scripts/tests/workspace/test_release_config.py`: a runner missing from the group fails; a runner in the group
  passes; a component the bundle doesn't ship fails; the real files pass.
- `contributing/releasing.md`, `docs/backstage/changelog.md`.
- No runtime code, and nothing for anyone who has installed troupe: there's been no release yet.
