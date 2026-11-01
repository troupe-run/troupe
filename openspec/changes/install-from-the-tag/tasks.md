# Tasks

## 1. The docs check refuses `main` on the install pages after a release (design D1, D4)

- [x] 1.1 In `scripts/tests/workspace/test_install_docs.py`, add the cases from the spec's "The install pages name the
  release once there is one", before any check code: `main` on `README.md` with the copied manifest at 0.1.0 is named
  with the page, the line and the full `--no-sources` tag command; `main` on `docs/opening-night/install.md` at 0.0.0
  passes; `main` on `packages/troupe-run/README.md` at 0.1.0 passes. Verify the first fails and the other two pass on
  the current check (`uv run pytest scripts/tests/workspace/test_install_docs.py`), and record that here.
  - 2026-11-01, before the check: `-k main_on` gave 1 failed, 2 passed. The README case failed with `assert [] ==
    ['README.md:19 gives the install command with main, but …']`: the current check says nothing.
    `given()` sets a copy's page to any ref, so the cases don't depend on what the real pages give.
- [x] 1.2 In `problems()`, refuse a `main` command on `INSTALL_PAGES` while `release_config.bundle_version()` isn't
  0.0.0, with the message in design D1. Verify the three cases from 1.1 pass, each asserting the whole message, and
  that every existing case still passes.
  - The existing cases could only pass once the real pages gave the tag (2.1, 2.2): with the manifest at 0.1.0, the
    refusal names the real pages' `main`. After 2.2, all 18 pass.
  - Also per D1: on the two install pages after a release, the check's other fixes (a malformed command, a page with
    no command) now suggest the tag command, not `main`'s, which would be refused there. The subdirectory case
    asserts it, and a new case covers the no-command message, which had no test before.

## 2. The install pages give the tag (design D2, D3, D4)

- [x] 2.1 In `README.md` and `docs/opening-night/install.md`, replace the command between the markers with
  `uv tool install --no-sources "git+https://github.com/troupe-run/troupe@troupe-run-v0.1.0#subdirectory=packages/troupe-run"`.
  Rewrite the prose around it per D2 and D3: it installs the latest release; for another release, its tag from the
  releases page; for `main` or a commit, put it in place of the tag and leave out `--no-sources`; to move to a newer
  release, run the install command again with its tag; `uv tool upgrade troupe-run` only for an install of `main`.
  Name no version outside the markers. Verify `grep -n "0\.1\.0" README.md docs/opening-night/install.md` finds only
  the two command lines, and read both pages through.
- [x] 2.2 Rework the docs tests that start from `MAIN` on the real pages (`tagged()`, the core's-tag case, the
  end-marker case) to start from the tag command, per D4, keeping what each checks. Update the module docstring's #208
  note to say the pages give the tag. Verify `uv run pytest scripts/tests/workspace/test_install_docs.py` passes,
  including `test_every_install_command_in_the_docs_is_the_one_the_install_check_runs` on the real pages.
  - 2026-11-01: `tagged()` and `MAIN` are gone. `given(root, page, ref)` sets a page's command to any ref, and
    `released(root, version)` sets the manifest and both install pages together, as a release pull request does
    (`main` at 0.0.0, the tag otherwise). So no case depends on the version the real pages give, and none breaks when
    a release moves them to 0.2.0. The end-marker case for `main` now runs at 0.0.0, since at a release `main` is
    refused before the markers are looked at. 18 passed.
- [x] 2.3 Run release-please's generic updater (release-please 17.6.0, the version `release.yml`'s action locks, from
  npm in the scratchpad) on copies of both new pages with a new version of 0.2.0. Verify the only change in each is the
  command line, to `@troupe-run-v0.2.0`, with `--no-sources` kept. Record the diffs here.
  - 2026-11-01: `release.yml` still pins `release-please-action` v5.0.0, which locks release-please 17.6.0. Installed
    it from npm into the scratchpad and ran `new Generic({version: Version.parse("0.2.0")}).updateContent(page)` on
    copies of both pages. Each diff was the command line only, `@troupe-run-v0.1.0` to `@troupe-run-v0.2.0` with
    `--no-sources` kept (README.md:19, install.md:18). The prose, which names no version, was unchanged.
- [x] 2.4 In `contributing/releasing.md`, "Checking each release's install", replace "While the command says `@main`
  (until #208 switches it after 0.1.0), there's nothing for it to change." with the pages naming the tag from 0.1.0
  on, and add that the docs check refuses `main` on them once there's a release. Verify by reading it against the
  pages and the check.

## 3. Check the install the pages give

- [x] 3.1 In a scratch `UV_TOOL_DIR` and `UV_TOOL_BIN_DIR`, run the README's command exactly as written and the
  installed `troupe --version`. Verify it prints troupe 0.1.0 and protocol 0.1.0, then remove the scratch directories.
  Record the result here.
  - 2026-11-01, macOS (arm64), uv 0.13.6: the README's command, taken from between its markers, installed 22
    packages and printed `troupe 0.1.0 (protocol 0.1.0)`. The scratch directories were removed.
- [x] 3.2 Run `uv run scripts/check.py` and verify it passes.
  - 2026-11-01, macOS: all gates passed, 3361 passed and 14 skipped (platform-only and opt-in tests).

## Workflow follow-up

- Open the draft pull request with `Closes #208`, citing release install check run 41290734956 (all 12 legs on
  Linux, macOS and Windows, Python 3.12 to 3.15) as the check against the real tag.
- After the merge, comment on #208 with the pull request, the archived change and that run, and check its card on
  the roadmap board says Done.
