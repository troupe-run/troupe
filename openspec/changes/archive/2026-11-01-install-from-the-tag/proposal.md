# Proposal

## Why

0.1.0 is cut: `troupe-run-v0.1.0` exists, and its release install check
([run 41290734956](https://github.com/troupe-run/troupe/actions/runs/41290734956)) passed on Linux, macOS and
Windows, on Python 3.12 to 3.15. But the README and the install page still tell people to install `@main`, and while
they do, each release pull request has nothing to move (`contributing/releasing.md`, "Checking each release's
install"). #208 switches the documented command to the tag, so people install the release and every later release
pull request keeps the command on the newest one. #189 and install-from-tag built everything else for this.

## What Changes

- **The README and the install page give the tag.** Between their release-please markers, the command becomes
  `uv tool install --no-sources "git+https://github.com/troupe-run/troupe@troupe-run-v0.1.0#subdirectory=packages/troupe-run"`.
  The prose around it now leads with the release, and says how to install `main` or a commit instead, in words that
  stay true when a release pull request moves the version (design D2).
- **Upgrading is described as it works for a tag.** `uv tool upgrade troupe-run` on a tag install prints "Nothing to
  upgrade" (checked 2026-11-01, uv 0.13.6), because the tag pins it. Both pages say to run the install command again
  with the newer tag. Running it with another ref replaces the install, without `--force`. `upgrade` stays documented
  for an install of `main` (design D3).
- **Once the bundle has a release, the install pages can't go back to `main`.** The docs check refuses a `main`
  command in the README or the install page while the manifest gives `troupe-run` a released version, naming the page,
  the line and the tag command to give. Without it, a slip back to `@main` would pass every check, and release pull
  requests would quietly stop moving anything. Other pages, such as `packages/troupe-run/README.md`, still give `main`
  or a commit, since no release moves them (design D1).
- **`contributing/releasing.md` drops "until #208 switches it"**: the command names the tag from 0.1.0 on.
- **The install check against the tag is recorded, not re-run.** It already ran when the release was published. Its
  run is cited in the pull request and on #208 when it closes. No new workflow or script change is needed for it.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `installation`: a new requirement, "The install pages name the release once there is one": the README and the
  install page give the bundle's tag once the manifest has a release, and the docs check refuses `main` there. "The
  install command is documented in one form" keeps its text, but its "page and check agree" scenario now names the
  released tag rather than `main`. "Each release moves the documented tag" is unchanged; its "Before the first tag"
  scenario still holds.

## Impact

- `README.md`, `docs/opening-night/install.md`: the command names `@troupe-run-v0.1.0` with `--no-sources`; the
  prose about refs and upgrading changes to match.
- `scripts/tests/workspace/test_install_docs.py`: the new refusal, and its existing tests reworked because the real
  pages no longer give `main` (the `tagged()` helper and the end-marker case start from it). Its docstring's #208
  note goes.
- `contributing/releasing.md`: the `@main` sentence.
- `packages/troupe-run/README.md`: unchanged. It isn't moved by releases, so it can't name a tag (install-from-tag
  design D3); it already points to the install page.
- No code in `packages/` or `plugins/` changes, and nothing changes for anyone who has installed troupe.
