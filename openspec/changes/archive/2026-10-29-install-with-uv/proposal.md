# Proposal

## Why

Nobody outside this repository can install troupe yet: the README says there's nothing to install, and the user docs'
install page says how is undecided (#144). #139 decided that a documented uv install is enough for 0.1.0, with PyPI not
assumed. A plain `uv tool install` of `packages/troupe` isn't enough, though. It installs core alone, and core finds its
adapters by entry point and starts its runners as `python -m <runner>` in its own environment. So an install has to bring
six adapters and two runner plugins into troupe's environment, and nothing yet says how.

## What Changes

- **A bundle package, `troupe-run`** (`packages/troupe-run/`), that depends on `troupe`, on every adapter under
  `packages/` and on every runner plugin under `plugins/`, and provides the `troupe` command. Core keeps no dependencies
  that exist only for distribution (owner, 2026-10-29). The root's workspace sources pin every one of them to the same
  commit, so one URL installs everything:
  `uv tool install "git+https://github.com/troupe-run/troupe@main#subdirectory=packages/troupe-run"`.
- **The check fails** when a workspace member is missing from the bundle's dependencies, when the bundle's `troupe`
  command isn't core's, or when core's own dependencies name an adapter or plugin.
- **One named place holds the install command**, and the README, the install page and the install check all use it.
- **An install check** (`scripts/install_check.py`) runs that command against a given commit into a throwaway tool
  directory, then runs the installed `troupe`: `--version`, and a scripted performance in a fresh theatre outside the
  checkout. CI runs it against the commit under test on Linux, macOS and Windows, on every supported Python.
- **The README and `docs/opening-night/install.md`** say how to install with uv from `main` or a given commit, which
  Python versions troupe needs (3.12 to 3.15, which uv provides), and that no release exists yet.
- **Installing by release tag moves to #189** (0.2.0, owner, 2026-10-29). No tag exists, and 0.1.0 is released only
  when its milestone's last issue closes (#139), so this change can't check a command against one. #189 switches the
  docs to tags and checks each release's tag on all three platforms.
- **The user docs' issue links match #139's split.** `docs/the-company/escalation.md` sends reaching a role to #148,
  not #62. Every other link to #62 or #124 is checked against what those issues now mean: #62 is gates only, each
  addressed to whoever runs troupe, and #124 is only the first flow, a sequence. Pages that say otherwise are corrected.

## Capabilities

### New Capabilities

- `installation`: how someone outside the repository installs troupe with uv. Covers the bundle package and what it
  must contain, the `troupe` command it provides, the one documented install command, and the check that runs it on
  every platform.

### Modified Capabilities

None. The bundle is a member under `packages/`, so the existing `releases` requirements already put it in the linked
group, with its own changelog. The docs' link fixes change page content, not the `user-docs` requirements.

## Impact

- New `packages/troupe-run/` (pyproject, README, LICENSE, a module that holds nothing but its docstring), plus its
  entries in `release-please-config.json`, `.release-please-manifest.json`, the root `pyproject.toml` (workspace
  source and tool lists), `scripts/check-paths.toml` and `uv.lock`.
- New `scripts/install_check.py` and tests for the bundle's contents. `.github/workflows/ci.yml` runs the install
  check in each check leg.
- `README.md`, `docs/opening-night/install.md`, `docs/backstage/changelog.md` (the bundle's changelog), and the pages
  that link #62 or #124: `docs/the-company/escalation.md`, `gates-and-decisions.md`, `flows.md`,
  `docs/stagecraft/route-decisions.md`, `read-the-lineage.md`, `build-a-flow.md`.
- No change to core's behaviour or dependencies.
