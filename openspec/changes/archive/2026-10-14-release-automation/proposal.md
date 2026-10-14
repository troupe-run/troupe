# Proposal

Issue: troupe-run/troupe#23. It follows #22 (`workflow-guardrails`), whose design D11 moved commit-message checks on
GitHub into the `guard` check. This change keeps the release tool, the PR-title check and the two known snags (the
release PR's token, and `uv.lock`). The owner decided four questions on 2026-10-13, recorded in design D1, D3, D6
and D8.

## Why

Versions are still the bootstrap placeholder `0.0.1.dev0` in all eight workspace packages, and no changelog exists.
Every commit on `main` since the bootstrap is a Conventional Commit, and `guard` re-checks every push. So the
history can already produce versions and changelogs, and producing them by hand would only add mistakes. Now is the
moment to set this up: once packages ship, the first version number and the changelog's starting point can't be
changed.

## What Changes

- **release-please opens and maintains a release PR** for each batch of releasable commits on `main`. The PR bumps
  versions and writes changelogs. When it's merged, release-please tags the commit and creates the GitHub releases.
  It runs from a `release` workflow on every push to `main`.
- **Versioning follows the repo's layout.** Core and its bundled adapters (`packages/*`) share one linked version.
  Each plugin (`plugins/*`) has its own version, so it can be split into its own repo later. Every package has its
  own `CHANGELOG.md`. The protocol (`protocol/`) is in the core's linked group with a changelog of its own, so a
  contract change releases the core.
- **Pre-1.0 semver:** a breaking change bumps the minor version, and the first release is 0.1.0 for every package.
- **The release PR is opened with a dedicated GitHub App's token**, so the required CI runs on it (a PR opened with
  `GITHUB_TOKEN` triggers no workflows). The App is new and narrow: contents, pull requests and issues on
  `troupe-run/troupe` only. Its commits carry a DCO sign-off, because DCO is a required check.
- **The release PR keeps `uv.lock` in step.** It bumps each package's version in `uv.lock` along with its
  `pyproject.toml`, so `uv sync --locked` passes in CI.
- **A test keeps the release config complete.** It fails when a workspace member is missing from the config, the
  linked group or the manifest, or when a package's lock entry isn't updated.
- **Prerequisites, done in `troupe-run/infrastructure`**, where `guard.py` and `guard.yml` are maintained and
  delivered from, and where the org's setup is declared:
  - #33 (PR#37): the release PR's branch passes the branch-change rule, but only on troupe, and only when the App
    authored every commit it adds to `main`;
  - #33 (PR#37): a **PR-title check** as a backstop. Squash merging is off today (the ruleset allows rebase only), so
    a title never becomes a commit. If squash is turned back on, the title becomes the commit message, and it has
    to be checked already;
  - #34 (PR#41): the release App's environment, variable and labels, and a `release branches` ruleset that lets only
    the App write `release-please--*` branches. A commit's author is self-declared, so this ruleset, not the author
    check, is what makes the exemption safe;
  - #42 (PR#44): the exemption opened with the bot's address, on troupe only.
- **Scopes stay free-form** (lowercase kebab-case, as `guard` already enforces). Restricting them to the `cap:*`
  list is deferred: most commits use `openspec` or `guard`, which aren't capabilities.

Out of scope: making checks required (done in troupe-run/infrastructure#1's `required-checks`), and publishing to
PyPI or a brew tap (nothing is installable yet).

## Capabilities

### New Capabilities
- `releases`: how troupe's packages get versions, changelogs and releases: derived from Conventional Commits on
  `main`, pre-1.0 rules, the linked core group and independent plugins, and a release PR that passes every
  required check, `uv.lock` included.

### Modified Capabilities
(none in this repo. The PR-title and release-branch rules change `development-workflow`, which lives in
troupe-run/infrastructure.)

## Impact

- New: `.github/workflows/release.yml`, `release-please-config.json`, `.release-please-manifest.json`, a
  `CHANGELOG.md` per package (written by the first release PR), `docs/releasing.md`, and a test in `scripts/tests/`.
- `pyproject.toml` versions and `uv.lock` change only through release PRs, from `0.0.1.dev0` to `0.1.0` on the first
  one.
- troupe-run/infrastructure: done, as listed above. The guard is delivered to troupe's `main`, and the `release`
  environment, `RELEASE_APP_CLIENT_ID`, the `autorelease: pending` and `autorelease: tagged` labels and the
  `release branches` ruleset are applied.
- Owner, by hand: done. The owner created the App, which can't be done through the API, and set its private key as
  the `release` environment's secret. Secret values are never managed by OpenTofu.
- Tags: `<component>-v<version>` per component. A core release tags all seven linked packages and the protocol,
  plus one tag per plugin that released.
