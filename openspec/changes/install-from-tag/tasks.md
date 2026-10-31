# Tasks

## 1. The install check installs from GitHub by a tag (design D1, D4)

- [x] 1.1 In `scripts/install_check.py`, add `TAG_PREFIX = "troupe-run-v"` beside `TEMPLATE`, and a function giving the
  version a ref names when it's `TAG_PREFIX` + version (`None` otherwise). Verify with unit tests in
  `scripts/tests/workspace/test_install_check.py`: `troupe-run-v0.1.0` gives 0.1.0; `troupe-v0.1.0`, `main`, a SHA
  and `troupe-run-v` alone give `None`.
- [x] 1.2 Add `--hosted`: install from `REPOSITORY` with the ref exactly as given, still resolving the ref in the
  checkout to read core's version. Verify with tests that the arguments uv gets for `--hosted --ref troupe-run-v0.1.0`
  are the URL `command(REPOSITORY, "troupe-run-v0.1.0")` holds, and that without `--hosted` they're unchanged
  (`file://` URL and the resolved SHA).
- [x] 1.3 For a `troupe-run-v<version>` ref, fail unless `<version>` equals core's version at the commit and the
  installed `troupe --version` prints it, naming the tag and the version found. Verify with tests for both failures,
  each asserting the whole message, written to fail on main first.
- [ ] 1.4 Update the script's docstring and usage for `--hosted` and tags. Push the branch, then run
  `uv run scripts/install_check.py --hosted --ref <pushed head SHA>` on macOS, and record the result here. It's the first
  install from the hosted URL.

## 2. The docs accept the bundle's tag at its released version (design D2, D3)

- [ ] 2.1 In `scripts/tests/workspace/test_install_docs.py`, take the allowed refs from the root: `main`, `<commit>`, and
  `TAG_PREFIX` + `troupe-run`'s version in `.release-please-manifest.json`, with 0.0.0 refused as "no release yet".
  Verify with copy-the-real-pages tests: core's tag (`@troupe-v0.1.0`) is named with page, line and expected command;
  `@troupe-run-v0.1.0` with the manifest at 0.0.0 is named with version 0.0.0; the same line with a copied manifest
  set to 0.1.0 passes.
- [ ] 2.2 Add the markers check: in `README.md` and `docs/opening-night/install.md`, a command naming `main` or a
  `troupe-run-v` tag must sit between `<!-- x-release-please-start-version -->` and `<!-- x-release-please-end -->`,
  and anywhere else a tagged command must too. Verify with tests: a command moved after the end marker is named with
  page and line; the `<commit>` command outside the markers passes.
- [ ] 2.3 Put the markers around the `@main` code block in `README.md` and `docs/opening-night/install.md`, outside the
  fences, leaving the `<commit>` block outside. Change "Installing by release tag comes with the first release (#189)"
  in both to say releases are installed by the bundle's tag, `troupe-run-v<version>`, from the first release (#208).
  Check `packages/troupe-run/README.md` says the same where it names the refs. Verify that the docs tests pass on the
  real pages (`uv run pytest scripts/tests/workspace/test_install_docs.py`) and that both pages read correctly.

## 3. Each release moves the documented tag (design D3)

- [ ] 3.1 Add `{"type": "generic", "path": "/README.md"}` and `{"type": "generic", "path":
  "/docs/opening-night/install.md"}` to the `packages/troupe-run` entry's `extra-files` in `release-please-config.json`.
- [ ] 3.2 In `scripts/release_config.py`, fail when the bundle's entry doesn't list both pages, naming the file and the
  missing path. Verify with a test in `test_release_config.py` that removes one, written to fail before 3.1, and that
  `test_every_workspace_member_is_configured_for_release` still passes.
- [ ] 3.3 Run release-please's generic updater, from npm at the version `release.yml`'s action pins, on scratch copies
  of both pages with `@main` replaced by `@troupe-run-v0.1.0` and a new version of 0.2.0. Verify that the diff changes
  only the tag to `troupe-run-v0.2.0`, and that the same run on the real pages (`@main`) changes nothing. Record the
  command and diffs here.

## 4. The release install check workflow (design D5, D6)

- [ ] 4.1 Write `scripts/release_check_report.py`, standard library only: from `gh run view --json jobs` output, the
  failed legs (platform, Python, job URL). From those, the tag, the run URL and the release URL, the issue's title and
  body. Verify with tests in `scripts/tests/workspace/` against a payload copied from a real `gh run view --json jobs`
  of a CI run with a failed leg: one failed leg, several, and none (no issue).
- [ ] 4.2 Write `.github/workflows/release-install-check.yml`, following `ci.yml`'s conventions (actions pinned by SHA,
  `timeout-minutes`, least permissions): `release: published` and `workflow_dispatch` with `ref`; the `install` matrix
  job filtered to `troupe-run-v` tags; the `report` job on failure for a tag only, with `contents: read`,
  `actions: read` and `issues: write`. Verify with `actionlint`, if the guard or check runs it, and by reading it
  against D5.
- [ ] 4.3 Extend `scripts/python_versions.py` to check the new workflow's `python` matrix like `ci.yml`'s, and add a
  test that the workflow's tag filter is `install_check.TAG_PREFIX`. Verify with tests that a matrix missing 3.15
  names the workflow and 3.15, and that a filter of `troupe-v` is named.
- [ ] 4.4 Check, in a `troupe-run/infra-probe-*` repository (troupe-run/infrastructure#217), whether a workflow's
  `GITHUB_TOKEN` with `issues: write` can create an issue with type Bug. Record the result in design D6. If it can't,
  make the report job use the `bug` label, with the body asking for the type, and update its test.
- [ ] 4.5 Add "Checking each release's install" to `contributing/releasing.md`: what runs on a published
  `troupe-run-v*` release, that release-please moves the documented tag, what the Bug means, and how to re-run with
  `gh workflow run release-install-check.yml -f ref=<tag>`. Verify that its links resolve, and that it matches the
  workflow as written.

## 5. Integration

- [ ] 5.1 Run `uv run scripts/check.py` and confirm it passes in full. Run `openspec validate install-from-tag --strict`.
- [ ] 5.2 On the draft PR's CI, once it's ready, confirm every leg's existing install check (from the commit) still
  passes on all three platforms.

## Workflow follow-up

- Raise with the owner the follow-up from design's Risks: a plugin-only release makes no `troupe-run` tag, so tag
  installs don't get it until the linked group next releases.
- After merge, dispatch the workflow once against `main` (`gh workflow run release-install-check.yml -f ref=main`) and
  confirm all legs pass. That's the first run on all three platforms from the hosted URL. Check first that the guard
  allows an agent to dispatch it. Otherwise ask the owner.
- #208 switches both commands to `@troupe-run-v0.1.0` once the release pull request has set the manifest to 0.1.0, and
  sees this workflow pass on the real tag.
- Archive on the branch before merge. After merge, comment on #189 with the PR and the archived change, close it, and
  check its card says Done.
