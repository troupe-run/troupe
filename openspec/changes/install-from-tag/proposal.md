# Proposal

## Why

troupe 0.1.0 will be installed with uv from its release tag (#139, #189), but no tag exists yet, so the documented
command still says `@main`. #189 is now in 0.1.0 for everything that doesn't need a tag (owner, 2026-10-31, in
troupe-run/infrastructure#230): the docs and the install check, ready for the tag form of the command. Switching the
documented command to the real tag, and seeing the check pass against it, is #208, after 0.1.0 is cut. This change
builds the parts that mean #208 only has to edit one line.

## What Changes

- **The tag form is settled: the bundle's own tag, `troupe-run-v<version>`** (owner, 2026-10-31). It names the package
  the command installs, and the name `uv tool list`, `upgrade` and `uninstall` show. Core's `troupe-v<version>` points
  at the same commit while the packages are linked, but it names a different package from the one installed.
- **The docs accept the tag form, with the bundle's current version.** The docs test that keeps every copy of the
  install command in one form also allows `@troupe-run-v<version>`, but only where `<version>` is `troupe-run`'s
  version in `.release-please-manifest.json`. That version is 0.0.0 until the release, so no copy can name a tag
  that doesn't exist yet. The README and the install page keep `@main` until #208. Their prose names the tag form
  in words that stay true in 0.1.0's own copy of the docs (design D7).
- **The documented tag follows each release** (owner, 2026-10-31). release-please markers go around the install
  command in the README and the install page, and the bundle's release entry updates both files. Each release pull
  request then moves the documented tag in the same commit as the versions. While the command says `@main`, the
  markers have nothing to replace. A docs check fails when a tagged command sits outside the markers.
- **The install check can install from GitHub by a tag.** `scripts/install_check.py` gains `--hosted`, which installs
  from `https://github.com/troupe-run/troupe` with the ref exactly as given, as the docs do, rather than from the
  checkout by commit. When the ref is a `troupe-run-v<version>` tag, the installed `troupe --version` must print that
  version.
- **A workflow checks every release's tag on all three platforms.** A new workflow runs on `release: published` for
  `troupe-run-v*` tags. It also runs on `workflow_dispatch` with a ref, to re-run it or to try it against `main`. On
  Linux, macOS and Windows, on every supported Python, it runs the install check with `--hosted` against the tag,
  which includes running the installed `troupe`.
- **A failed check on a published tag opens a Bug** (owner, 2026-10-31). Tags are never moved or deleted, so the
  release stays as it is. The workflow opens a Bug issue in troupe naming the tag, each failed platform and Python,
  and the run. The fix ships as the next patch release. The workflow's token can only write issues, and adding the
  issue to the roadmap board stays a manual step.
- **The new workflow's Python matrix is checked**, like CI's: it must list exactly the supported versions.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `installation`: the documented command may name the bundle's tag at its current version, inside release-please's
  markers, and each release moves it. The install check can install from GitHub by a ref. A new requirement: each
  published `troupe-run` tag is checked on every platform and Python, and a failure opens a Bug.

## Impact

- `scripts/install_check.py` and its tests: `--hosted`, and checking the version a tag names.
- `scripts/tests/workspace/test_install_docs.py`: the tag form, the manifest's version, and the markers.
- `release-please-config.json`: two `extra-files` on the `packages/troupe-run` entry (`/README.md`,
  `/docs/opening-night/install.md`). `scripts/release_config.py` already allows extra entries beside the lock update.
- `scripts/python_versions.py`: the new workflow's matrix is checked against the supported versions.
- `.github/workflows/`: a new release install check workflow, with `contents: read` and `issues: write`.
- `README.md`, `docs/opening-night/install.md`: markers around the command, and the tag form and #208 in place of
  "comes with the first release (#189)". The command itself stays `@main`.
- `contributing/releasing.md`: what the release install check does, and what to do when it opens a Bug.
- Nothing changes for anyone who has installed troupe. #208 switches the documented ref to `troupe-run-v0.1.0`.
