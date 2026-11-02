# Proposal

## Why

Dependabot's scheduled `uv` job in troupe has failed on every run so far (2026-10-26, 2026-10-27, 2026-11-02), with
`dependency_file_not_resolvable` (#254). It treats each workspace member as a dependency and looks it up on PyPI. The
name `troupe` there belongs to an unrelated, active project (KevinIssaDev/troupe, 0.5.2), so Dependabot runs
`uv lock --upgrade-package troupe==0.5.2`, which can never resolve against the workspace member `troupe` 0.1.0. The
same command fails locally, word for word. The bundle's pins (#228) aren't the cause: the first two failures came
before them.

A workspace member's version only ever moves through its own release (spec: releases), so Dependabot has nothing to
propose for one. Any member whose name appears on PyPI, ours or a squatter's, breaks the job the same way.

## What Changes

- **In troupe-run/infrastructure (#259), merged alongside:** the Dependabot policy can declare names to ignore per
  repository and ecosystem, and troupe's `uv` entry ignores `troupe` and `troupe-*`. The delivered
  `.github/dependabot.yml` carries them. This is where the failure is fixed; troupe can't edit the delivered file.
- **In troupe:** a check, run by `scripts/check.py`'s tests, that every workspace member's name is matched by an
  ignore in the `uv` entry of the delivered `.github/dependabot.yml`. A member left uncovered (for example, one named
  outside `troupe-*`) fails the check, naming the member and saying to add it to infrastructure's Dependabot policy.
  A delivered file with no `uv` entry, or an unreadable one, fails too, rather than passing.
- `contributing/releasing.md`'s "Adding a package" says why a new member must be covered, and where to change it.
- Out of scope: publishing troupe's packages to PyPI. It wouldn't fix this (`troupe` is taken), and how troupe is
  installed is decided by #208.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `releases`: adds a requirement that Dependabot proposes no version for a workspace member, kept true by the check.

## Impact

- New `scripts/dependabot_members.py` and its tests in `scripts/tests/workspace/`. Reads the root `pyproject.toml`,
  each member's `pyproject.toml` (through `release_config.members`) and `.github/dependabot.yml`.
- `contributing/releasing.md`.
- The troupe check fails until infrastructure#259 delivers the ignore, so the infrastructure PR is applied first and
  the troupe PR is rebased on the delivery commit.
- No change to `uv.lock`, any package, or any spec's Purpose, so no `oob/troupe-spec-purposes.json` update.
