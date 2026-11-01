# Design

## Context

See proposal.md, "Why". What shapes the approach:

- **install-from-tag built the switch to be one line.** The README and the install page hold the command between
  `<!-- x-release-please-start-version -->` and `<!-- x-release-please-end -->`. The bundle's release entry runs
  release-please's generic updater on both pages, so a release pull request rewrites the version between the markers.
  `scripts/tests/workspace/test_install_docs.py` already accepts `@troupe-run-v<version>` with `--no-sources` on those
  two pages, at the manifest's version only, and refuses a tag on any other page (install-from-tag D2, D3;
  release-each-package D3).
- **The manifest gives `packages/troupe-run` 0.1.0**, and `troupe-run-v0.1.0` exists. Every component is pinned at
  0.1.0.
- **The release install check already ran against the tag.** `release-install-check.yml` ran on the published
  `troupe-run-v0.1.0` release (run 41290734956, 2026-11-01): all 12 legs passed, Linux, macOS and Windows on Python
  3.12 to 3.15, each with a scripted performance. No Bug was opened.
- **uv leaves a tag install where it is.** Checked 2026-11-01 with uv 0.13.6, in a scratch `UV_TOOL_DIR`: after
  installing `@troupe-run-v0.1.0` with `--no-sources`, `uv tool upgrade troupe-run` printed "Nothing to upgrade".
  Running `uv tool install` again with `@main` replaced the install without `--force`.
- **The docs test's helpers start from the real pages giving `main`.** `tagged()` replaces `MAIN` with the tag, and
  the end-marker case replaces `MAIN` too. Both assert `MAIN` is on the page, so they fail once it isn't.

## Goals / Non-Goals

**Goals:**

- Someone following the README or the install page installs the latest release.
- Once switched, the pages can't silently go back to `main`, which would leave release pull requests nothing to move.

**Non-Goals:**

- Running the install check against the tag again. It ran when the release was published, and the tag can't change.
  The pull request and #208 cite that run. If it's ever needed again, `gh workflow run release-install-check.yml -f
  ref=troupe-run-v0.1.0` runs it.
- Naming the tag in `packages/troupe-run/README.md`. No release moves it, so the docs check refuses a tag there
  (install-from-tag D3). It already sends people to the install page.
- Changing the install check, the release workflows or release-please's configuration.

## Decisions

### D1. Refuse `main` on the two install pages once there's a release

The docs check's `main` case on `README.md` and `docs/opening-night/install.md` becomes conditional on the manifest:
at 0.0.0 it passes as now; at a released version it fails with
`<page>:<line> gives the install command with main, but <manifest> gives packages/troupe-run <version>: give '<tag command>'.`
The message names the full command, `--no-sources` included, so it can be pasted. `main` stays allowed on every other
page, and `<commit>` stays allowed everywhere.

- *Alternative: no check, just the edit.* The issue's "done when" asks only for the switch. But a revert to `@main`
  would then pass every check, and nothing would say that release pull requests had stopped moving the tag. That's
  the quiet fall-through the project's rules refuse. The check is a few lines beside the existing tag checks.
- *Alternative: refuse `main` on every page.* `packages/troupe-run/README.md` can't name a tag (no release moves it),
  so it would have no valid command at all. A commit placeholder alone would be less useful there.

### D2. Prose that stays true when a release moves the version

The release updater only rewrites what's between the markers. So the prose outside them names no version: it says the
command installs "the latest release", and points to the tag form `troupe-run-v<version>` and the releases page for
others. Installing `main` or a commit is given as "put `main` (or a commit) in place of the tag, and leave out
`--no-sources`", since the plain form is what `main` and a commit need. The install page keeps its `<commit>` code
block, outside the markers, as now. The README keeps it short.

- *Alternative: give a second, `@main` code block.* On the two install pages a `main` command is refused (D1), and
  outside the markers it's refused already. Prose avoids both.

### D3. Upgrading is described per kind of install

For a release: run the install command again with the newer tag (it replaces the install). For `main`:
`uv tool upgrade troupe-run` moves it to the latest `main`. Both pages say this. The README says only the release
case and the `main` case in one line each.

### D4. Rework the docs tests around the tagged pages

The real pages give the tag now, so the tests that edited `MAIN` on them start from the tag command instead. `tagged()`
becomes a helper that sets a copy's page to a given ref (`main` included, for the pre-release cases with the manifest
at 0.0.0). Each existing case keeps what it checks; each new case is written to fail before the check exists: `main`
on the README at 0.1.0 is named with the tag command; `main` on the install page at 0.0.0 passes; `main` on
`packages/troupe-run/README.md` at 0.1.0 passes.

## Risks / Trade-offs

- [The pages name a pre-release.] 0.1.0 is published as a GitHub pre-release, and the install page carries
  `prerelease: true`. → That's what the project is: the README already says pre-alpha. No wording change is needed for
  it.
- [A release pull request's generic updater could rewrite more than the tag.] It rewrites semver strings between the
  markers, and only the command line sits there. → The docs check fails a release pull request whose command doesn't
  match the manifest, so a bad rewrite can't merge.
- [The site builds the install page from `main`.] troupe.run's docs show the tag as soon as this merges. → The tag
  exists and passed its install check, so that's correct from the moment it's published.
