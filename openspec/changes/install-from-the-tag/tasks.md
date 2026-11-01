# Tasks

## 1. The docs check refuses `main` on the install pages after a release (design D1, D4)

- [ ] 1.1 In `scripts/tests/workspace/test_install_docs.py`, add the cases from the spec's "The install pages name the
  release once there is one", before any check code: `main` on `README.md` with the copied manifest at 0.1.0 is named
  with the page, the line and the full `--no-sources` tag command; `main` on `docs/opening-night/install.md` at 0.0.0
  passes; `main` on `packages/troupe-run/README.md` at 0.1.0 passes. Verify the first fails and the other two pass on
  the current check (`uv run pytest scripts/tests/workspace/test_install_docs.py`), and record that here.
- [ ] 1.2 In `problems()`, refuse a `main` command on `INSTALL_PAGES` while `release_config.bundle_version()` isn't
  0.0.0, with the message in design D1. Verify the three cases from 1.1 pass, each asserting the whole message, and
  that every existing case still passes.

## 2. The install pages give the tag (design D2, D3, D4)

- [ ] 2.1 In `README.md` and `docs/opening-night/install.md`, replace the command between the markers with
  `uv tool install --no-sources "git+https://github.com/troupe-run/troupe@troupe-run-v0.1.0#subdirectory=packages/troupe-run"`.
  Rewrite the prose around it per D2 and D3: it installs the latest release; for another release, its tag from the
  releases page; for `main` or a commit, put it in place of the tag and leave out `--no-sources`; to move to a newer
  release, run the install command again with its tag; `uv tool upgrade troupe-run` only for an install of `main`.
  Name no version outside the markers. Verify `grep -n "0\.1\.0" README.md docs/opening-night/install.md` finds only
  the two command lines, and read both pages through.
- [ ] 2.2 Rework the docs tests that start from `MAIN` on the real pages (`tagged()`, the core's-tag case, the
  end-marker case) to start from the tag command, per D4, keeping what each checks. Update the module docstring's #208
  note to say the pages give the tag. Verify `uv run pytest scripts/tests/workspace/test_install_docs.py` passes,
  including `test_every_install_command_in_the_docs_is_the_one_the_install_check_runs` on the real pages.
- [ ] 2.3 Run release-please's generic updater (release-please 17.6.0, the version `release.yml`'s action locks, from
  npm in the scratchpad) on copies of both new pages with a new version of 0.2.0. Verify the only change in each is the
  command line, to `@troupe-run-v0.2.0`, with `--no-sources` kept. Record the diffs here.
- [ ] 2.4 In `contributing/releasing.md`, "Checking each release's install", replace "While the command says `@main`
  (until #208 switches it after 0.1.0), there's nothing for it to change." with the pages naming the tag from 0.1.0
  on, and add that the docs check refuses `main` on them once there's a release. Verify by reading it against the
  pages and the check.

## 3. Check the install the pages give

- [ ] 3.1 In a scratch `UV_TOOL_DIR` and `UV_TOOL_BIN_DIR`, run the README's command exactly as written and the
  installed `troupe --version`. Verify it prints troupe 0.1.0 and protocol 0.1.0, then remove the scratch directories.
  Record the result here.
- [ ] 3.2 Run `uv run scripts/check.py` and verify it passes.

## Workflow follow-up

- Open the draft pull request with `Closes #208`, citing release install check run 41290734956 (all 12 legs on
  Linux, macOS and Windows, Python 3.12 to 3.15) as the check against the real tag.
- After the merge, comment on #208 with the pull request, the archived change and that run, and check its card on
  the roadmap board says Done.
