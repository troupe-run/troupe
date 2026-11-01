# Tasks

## 1. Probe before relying on anything (design D9)

- [ ] 1.1 Ask the owner before creating the private probe repository `troupe-run/infra-probe-release-each-package`
  (auto mode refuses a public one). Set it up with a three-member uv workspace shaped like troupe: core, an adapter
  depending on core, and a bundle depending on both, with the bundle's first commit also touching `uv.lock`. Add
  release-please with this change's config shape (no linked group, `initial-version` 0.1.0, `bump-minor-pre-major`,
  the bundle's `exclude-paths`) and a `release.yml` copy that uses `GITHUB_TOKEN`. Verify that the repository's
  first push opens a release pull request, and record its URL here.
- [ ] 1.2 uv (D2, D3): with the bundle's dependencies pinned as direct references at the probe's tags, verify
  `uv sync --locked` installs every member from the workspace. Then verify the tagged
  `uv tool install --no-sources "git+https://github.com/…@<bundle-tag>#subdirectory=…"` installs each member from its
  pinned tag on Linux, macOS and Windows, with a matrix job that prints each installed member's version and file
  contents. Record the run here.
- [ ] 1.3 Bootstrap (D7): verify the first release pull request releases core and the adapter at 0.1.0 and leaves
  the bundle out, and record whether `exclude-paths` is repository- or package-relative. If the bundle is included,
  try the fallback (a lightweight `<bundle>-v0.0.0` tag, no GitHub release) and record the result. If neither works,
  stop and ask the owner before going on.
- [ ] 1.4 The two steps (D4–D6, after group 3's script exists, copied in): merge the first release pull request in
  the probe. Verify the pinning pull request opens typed `feat`, pins both members at `-v0.1.0` and removes
  `exclude-paths`, and that release-please leaves its branch alone. Merge it, and verify the next release pull
  request gives the bundle 0.1.0. Then a `fix:` to the adapter: the adapter releases alone, and the pinning commit
  is `fix`, bringing the bundle to 0.1.1. Then a `feat!:` to core: the pinning commit is breaking, bringing the
  bundle to 0.2.0. And a second release while a pinning pull request is open updates it. Record each pull request
  here, then delete the probe repository and record that it's gone.

## 2. Every package on its own (D1, D7, D8)

- [x] 2.1 In `scripts/tests/workspace/test_release_config.py`, write the new tests first, and record that they fail
  against the unchanged check:
  - a `linked-versions` plugin, under any group name, is refused with the spec's message;
  - pins with another repository, another subdirectory, or a malformed tag are refused, each naming the dependency,
    `packages/troupe-run/pyproject.toml` and the expected reference;
  - a pin above the manifest names both versions;
  - `exclude-paths` on the bundle is accepted only in D7's exact form, and only while the bundle's manifest version is
    0.0.0;
  - a bare dependency passes.

  Replace the linked-group tests (`test_a_package_left_out_of_the_linked_group_is_named`, the bundled-runner,
  not-shipped, not-a-member, without-the-bundle, protocol-in-the-group and missing-group tests): their rule no longer
  holds.
  - Against the unchanged check (2026-11-01): 34 of the new cases failed, the linked group and every malformed
    pin, early pin and exclusion case. A pin at or behind the released version already passed, as it should.
    `test_a_new_package_without_release_config_is_named` now asserts the whole list, which is the two config and
    manifest messages and nothing else.
- [x] 2.2 In `scripts/release_config.py`, replace `_group_problems` and `LINKED_GROUP` with the D8 checks, using
  stdlib parsing of the PEP 508 direct reference (name, URL, `@ref`, `#subdirectory=`). Keep `members`/`bundled`
  free of any `packages/troupe-run` literal (`check_paths_reach.py`, rule 4). Update the module docstrings. Verify
  that 2.1's tests pass, along with `uv run pytest scripts/tests/workspace/test_release_config.py
  scripts/tests/workspace/test_bundle.py scripts/tests/test_check_paths_reach.py`.
  - `test_release_config.py`, `test_bundle.py` and `test_check_paths_reach.py`: 145 passed. ruff, ruff format and
    mypy are clean. `bundled()` and `_group_problems` are gone. `REPOSITORY`, `pin()`, `pinned_version()` and
    `bundle_member()` are new, and pin_bundle.py and install_check.py will share them.
- [x] 2.3 In `release-please-config.json`, remove the `plugins` entry and add D7's `exclude-paths` (in the form 1.3
  found) to `packages/troupe-run`, or apply the fallback 1.3 chose. Verify that the file validates against release-please
  v17.6.0's `config.json` schema (`uvx check-jsonschema --schemafile <url> release-please-config.json`), and that
  `test_every_workspace_member_is_configured_for_release` passes on the real files.
  - 1.3's probe run showed the repository-relative form works, so the entry is
    `"exclude-paths": ["packages/troupe-run"]`. `uvx check-jsonschema` against v17.6.0's schema: "ok -- validation
    done". `test_every_workspace_member_is_configured_for_release` passes.
- [x] 2.4 Update the comment in `packages/troupe-run/pyproject.toml` that says the workspace sources install each
  dependency from the same commit, to say that a commit install does, and a tag install uses the pins. Commit it as
  `docs(bundle):` so it releases nothing. Verify with `git log -1 --format=%s` and that `uv run pytest
  scripts/tests/workspace/test_bundle.py` passes. If `bundle.py`'s parsing needs a pinned form, add a test that a
  pinned dependency counts as present.
  - The comment now covers both kinds of install. It's committed with the rest of group 2 as `build(release)`, which
    releases nothing either: the guard refuses a commit that leaves tracked edits out, so it can't go alone.
    `exclude-paths` keeps it out of #89 anyway. `bundle.py` already read pins by name. Two test changes:
    `test_the_bundle_names_each_dependency_bare_or_pinned_at_a_tag` replaces "without versions", which the first
    pin would have broken, and `test_a_pinned_dependency_counts_as_a_dependency` is new. `test_bundle.py`: 11
    passed.

## 3. The pinning step (D4, D5)

- [x] 3.1 Write `scripts/tests/workspace/test_pin_bundle.py` first, on copies of the real files with byte-exact
  writes (`write_bytes`), and record that it fails before the script exists:
  - no move when every pin matches the manifest, so no message file;
  - a bare dependency and one behind each move to `<name>-v<manifest version>`, and every other byte of the file is
    unchanged;
  - the bundle's own entry and the protocol are never pinned;
  - `exclude-paths` is removed from the bundle's config entry when present, and nothing else in the config changes;
  - each of `fix`, `feat` and breaking is chosen from changelog sections above the old pin, as in the spec's
    scenarios, using real release-please headings (copied from #89's changelogs);
  - the subject stays within 72 characters, and the `BREAKING CHANGE:` footer names each component and version;
  - a pin above the manifest, or a changelog missing a needed version, stops with a message naming the file.
  - Before the script existed, collection failed (`No module named 'pin_bundle'`). There are 20 cases. Each
    pyproject and config write is compared byte for byte, and CRLF endings are kept. The fixture's 0.1.0 changelog
    is #89's `troupe-vcs-git` one, shortened, and later sections use release-please's compare-link heading. The
    first pin is `feat!`, because every component's 0.1.0 has breaking changes from history. The last case shows
    the result passes `release_config.problems`, before and after the bundle's release.
- [x] 3.2 Write `scripts/pin_bundle.py` (stdlib only), sharing the reference parser with `release_config.py`. Its CLI
  is `uv run scripts/pin_bundle.py --message <path>`. Verify with 3.1's tests, `ruff`, `ruff format` and
  `mypy --strict`. Run it on this checkout, record that it moves nothing (every component is at 0.0.0), and that
  `git status` is clean afterwards.
  - `test_pin_bundle.py`: 20 passed. ruff, ruff format and `mypy --strict` are clean. Two fixes on the way: changelog
    paths in the footer now follow the components' order (a string sort put `-` before `/`), and a test's regex
    had the message's parts in the wrong order. On this checkout, `uv run scripts/pin_bundle.py --message <tmp>`
    exited 0, wrote no message file, and `git status` showed only the two new files. `scripts/pin_bundle.py` is
    listed in `check-paths.toml`'s scripts scope, and `test_check_scope.py` and `test_check_paths_reach.py` pass.

## 4. The release workflow (D6)

- [x] 4.1 In `.github/workflows/release.yml`, expose `releases_created` from `release-please`. Add the `pin-bundle`
  job (needs `release-please`, runs only when it's `true`, `release` environment, App token with `contents` and
  `pull-requests` write only, pinned action SHAs). It runs the script, commits as the App's bot with a sign-off on
  `release-please--pin-bundle` from `main`, force-pushes, and opens the pull request, or edits the open one.
  Add tests in `scripts/tests/test_ci_workflow.py`'s style (or a new
  `scripts/tests/workspace/test_release_workflow.py`) that pin the job's condition, its token's permissions, its
  environment and the branch name under `release-please--`. Verify they pass, and that `uvx zizmor` or the
  repository's workflow lint (whichever the check runs) is clean.
  - `scripts/tests/test_release_workflow.py` has 7 tests, which pass. They cover: the output, the condition, the
    environment, the token's two permissions, the branch matching `pin_bundle.BRANCH` and exempt by
    `guard.reserved_release_branch`, the bot matching the config's `signoff` (for DCO), and the checkout not
    persisting the token. The check runs no workflow linter, so I ran `uvx zizmor@1.16.3 --offline`. Its one finding,
    `artipacked`, is fixed: `persist-credentials: false`, and only the push uses the token. Now: "No findings".
    troupe's rulesets have no required-signatures rule, so a `git commit` signed off as the bot is enough.
- [ ] 4.2 Run the same job in the probe (1.4) and record that its pull request matches 3.1's expectations.

## 5. Installs from a tag (D3, D10)

- [x] 5.1 In `scripts/tests/workspace/test_install_check.py` and `test_install_docs.py`, write the new tests first
  and record that they fail:
  - the tag form has `--no-sources` and the `main`/commit form doesn't;
  - a page copy naming a tag without `--no-sources` fails with the expected command;
  - for a tag, the expected version is `troupe`'s pin, and a tag whose bundle version differs is refused;
  - a tag with a bare member dependency is refused before installing, naming it.
  - Against the unchanged check: 10 failed. That's 9 in `test_install_check.py` (the tag's form, from GitHub
    and from the checkout; the pinned version; a bundle version that differs; an unpinned component; no core
    pin; the printed-version message) and the new docs case.
- [x] 5.2 Change `scripts/install_check.py`: the command per ref kind, `expected_version` reading the bundle's
  `pyproject.toml` at the commit for a tag, and the bare-dependency refusal. Change its docstrings, which say the
  bundle and core share one version. Verify that 5.1's tests pass, and that `uv run scripts/install_check.py --ref
  HEAD` still installs and performs from the checkout.
  - `scripts/tests/workspace`: 215 passed. ruff and `mypy` (43 files) are clean. `uv run
    scripts/install_check.py --ref HEAD`: "installed and performed (run 46d8bb27-… succeeded)". The docs check
    (in `test_install_docs.py`) now recognises the command with or without `--no-sources`. It refuses a tag
    without the flag and a `main` or commit copy with it. `REPOSITORY` now lives in `release_config.py`, with
    `read_pin()` beside it for reading a tag's bundle. README and install page text is unchanged (`@main`).

## 6. Docs

- [ ] 6.1 `contributing/releasing.md`:
  - "What bumps what": each package on its own, the protocol as before, and no linked group (#218).
  - A new "The bundle follows its components" section: the pinning pull request, its type rule and branch, that the
    owner merges it, and the first release's `exclude-paths` bootstrap.
  - "Checking each release's install": the `--no-sources` tag form, and the expected version being core's pin.
  - "Adding a package": the bundle dependency in a non-releasing commit, pinned after its first release.

  Verify by reading each section against the config, the script and the workflow, and that
  `uv run pytest scripts/tests/workspace` passes.
- [ ] 6.2 `docs/backstage/changelog.md`: the runners no longer "release with troupe, at the same version". Each
  package has its own version, and `troupe-run`'s changelog lists the releases it ships. Verify with the user-docs
  tests in 7.1's check.

## 7. Integration

- [ ] 7.1 Run `uv run scripts/check.py` and `openspec validate release-each-package --strict`, and record both
  results here.

## Workflow follow-up

- Draft pull request closing #219; act on Claude's review; mark ready; archive on the branch; the owner merges.
- After the merge: check that the push regenerated #89 without `troupe-run` before the owner merges it. Then follow
  the migration plan (design) through the pinning pull request and the bundle's 0.1.0, and confirm the release
  install check passes against `troupe-run-v0.1.0` (#219's done-when).
- Comment on #219 with the PR and the archived change, check it's closed and its card is Done.
- Tell #208 that the tagged command now carries `--no-sources`.
- No Purpose changes, so no `oob/troupe-spec-purposes.json` update in infrastructure.
