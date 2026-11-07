# Tasks

## 1. Confirm what uv accepts before building on it (design D4, D10)

- [x] 1.1 In the scratchpad, with a throwaway `UV_TOOL_DIR` and `UV_TOOL_BIN_DIR`, confirm three things against this
  branch's commit. (a) `[project.optional-dependencies] all = []` in a copy of `troupe-run`'s `pyproject.toml`
  builds and installs. (b) `uv tool install "troupe-run[all] @ git+<repo>@<sha>#subdirectory=packages/troupe-run"`
  installs. (c) The same with `--no-sources` against `troupe-run-v0.1.0`, a tag whose base is all pinned, resolves
  without an index lookup for any workspace member. Verify: each command and its exit code recorded in the PR
  description. If any fails, stop and revise D4 or D10 before group 2.

## 2. The bundle's extras, and one reader of its requirements (design D2, D3, D4, D5; specs: installation, releases)

- [x] 2.1 Write the tests first, in `scripts/tests/workspace/`, with fixture manifests, a fixture `lm-studio` plugin
  that depends on a library, and a fixture runner table. They cover each scenario of installation's "A runner with
  dependencies beyond the SDK is an extra named after it", "The all extra installs every runner", the modified "One
  package installs troupe…" (an SDK-only runner in the base), runs' "The table and the bundle agree", and releases'
  "The bundle's extras are pinned like its dependencies" (a pin to another subdirectory, a bare member without the
  exclusion, the released SDK bare). Verify: each new test fails on main, run and shown.
- [x] 2.2 Add the shared reader to `scripts/release_config.py`. It yields each requirement in `dependencies` and in each
  extra, with where it came from. Switch `bundle.py`, `pin_bundle.py`, `release_config.py` (both reads) and
  `install_check.py` to it. Verify: the existing bundle, pinning, release-config and install-check tests pass
  unchanged, and `grep -n 'get("dependencies"' scripts/*.py` finds only the reader and core's own read in
  `bundle.py`.
- [x] 2.3 In `scripts/bundle.py`, add the rules for base or extra (D2), `all` (D4) and agreement with core's table
  (D5, read from `interim.py`'s source without importing core). Messages name the plugin, the extra, the file and
  where it belongs. Verify: 2.1's bundle tests pass.
- [x] 2.4 `pin_bundle.py`: a test where the `lm-studio` extra and `all` hold the same pin, and a release of the fixture
  runner moves both and nothing else. Verify: the test fails before 2.2's switch is used for rewriting and passes
  after.
- [x] 2.5 Add `[project.optional-dependencies]` with `all = []` to `packages/troupe-run/pyproject.toml`, with a comment
  citing this design (D2, D4), and run `uv lock`. Verify: `uv sync --locked` succeeds, and `uv run scripts/check.py`
  passes.
- [x] 2.6 Commit as `feat(bundle): ...` (subject ≤ 72 characters). Verify: `uv run scripts/check.py` passes before the
  commit.

## 3. Core refuses a known runner that isn't installed (design D5, D6; specs: runs, protocol)

- [x] 3.1 Write the tests first, in `packages/troupe/tests/`. They cover: a fixture table entry with `in_extra=True`
  and a package that doesn't exist, refused at perform and at `--rehearse` with `runner.not-installed`, with details
  `runner`, `package`, `extra: "lm-studio"`, a fix naming `troupe-run[lm-studio]` and the install page, and no run
  stream, run directory or worktree made; a base entry with a missing package, refused with no `extra` in its details and a fix
  naming the install page and `uv sync`; every real table entry having `in_extra` false today; and
  `schemas.plugin-missing`'s fix no longer saying "brings every runner". Verify: they fail on main, run and shown.
- [x] 3.2 Add `in_extra: bool = False` to `interim.Runner` and `interim.installed_runner()`. Call it from
  `runner_command`, `options_schema`, `options_validator` and perform's actor check, before anything is recorded.
  Reword `schemas.plugin-missing`'s fix in `core/schemas.py`. Verify: 3.1's tests pass.
- [x] 3.3 Catalogue `runner.not-installed`, with closed details (`runner`, `package`, `extra` only for a runner in an extra; config's
  actor path is the error's own `path`, per D6), in `protocol/schemas/error.schema.json`, copy it to `packages/troupe/src/troupe/protocol/`, and add it to
  `core/errors.py` with the failure exit code. Verify: the catalogue-agreement test and `protocol_guard` pass in a full
  run (a code that's catalogued but never raised fails the run), and `diff` of the two schema copies is empty.
- [x] 3.4 Commit as `feat(protocol): ...` for the code and catalogue, and `feat(runs): ...` for the refusal, if they
  split cleanly, otherwise one `feat(protocol)` commit. Verify: `uv run scripts/check.py` passes before each commit.

## 4. Config refuses only changes to that actor (design D7; spec: config)

- [x] 4.1 Write the tests first, in `packages/troupe/tests/` beside the config-kinds tests, with the fixture entry from
  3.1. They cover each scenario of config's two new requirements: defining or changing the actor is refused with
  `runner.not-installed` naming the actor's path, and nothing is recorded; removing it whole is recorded; moving it
  to `scripted` is checked against the scripted schema; changing another actor is recorded; a merge that changed its
  options isn't in conflict, and performing it afterwards is refused; and an unknown field on it in a merge is still a
  conflict. Verify: they fail on main, run and shown.
- [x] 4.2 Give `kinds.actor_problems` (and its callers in `kinds.check`, `check_actor` and the change path in
  `config/changes.py`) the set of actors a change touches, and apply D7. Verify: 4.1's tests pass, and the existing
  config and merge tests pass unchanged.
- [x] 4.3 Commit as `feat(config): ...`. Verify: `uv run scripts/check.py` passes before the commit.

## 5. Init refuses an uninstalled runner and names an installed runner's extra (design D8; spec: cli)

- [x] 5.1 Write the tests first, in the init tests. They cover: `troupe init --audition --runner <fixture>` refused
  with `runner.not-installed`, rehearsed or not, with no `.troupe/` made; with the fixture runner installed and in an
  extra, the perform step's notes naming `troupe-run[<runner>]` and the install page; and the scripted audition's
  notes mentioning no extra. Verify: they fail on main, run and shown.
- [x] 5.2 Call `installed_runner` from `audition()`, and add the extra note to `cli/init.py`'s `_step_notes` from
  `in_extra`. Verify: 5.1's tests pass, and the existing init tests pass unchanged.
- [x] 5.3 Commit as `feat(cli): ...`. Verify: `uv run scripts/check.py` passes before the commit.

## 6. The install check, CI and the install page cover the extras (design D9, D10; spec: installation)

- [x] 6.1 Write the tests first, in `scripts/tests/workspace/`. They cover: `command()` with and without extras, in
  both ref forms; the docs check accepting the extras form, refusing an extra `troupe-run` doesn't have, and refusing
  an install page whose list of extras differs from `troupe-run`'s; the tag pre-check failing on a bare runner in an
  extra; and the plan of steps the check runs for a fixture bundle with an `lm-studio` extra (base install, refusal
  rehearsal naming `troupe-run[lm-studio]`, the `[all]` install into a second tool directory, a rehearsal for every
  runner). Verify: they fail on main, run and shown.
- [x] 6.2 Extend `scripts/install_check.py` (`TEMPLATE`, `command()`, the tag pre-check, and steps (a) and (b) of D9,
  reading the extras and the table from the commit under test) and `scripts/docs_reference.py`. Verify: 6.1's tests
  pass, and `uv run scripts/install_check.py --ref HEAD` passes locally, its output showing both installs and the
  rehearsals.
- [x] 6.3 Update `docs/opening-night/install.md`. Add a "Runners that come as extras" section with the extras form
  between the release-please markers and the list of extras (today only `all`), and say a plain install has every
  runner in the base. Add a line to `packages/troupe-run/README.md`. The README keeps the plain form. Check the
  release-please config updates the new copy. Verify: the docs check passes, and `uv run scripts/check.py` passes.
- [ ] 6.4 Confirm `ci.yml`'s and `release-install-check.yml`'s install-check steps need no new arguments (the `[all]`
  install is part of the check), and that their timeouts cover two installs. Verify: on the PR's CI, every platform
  and Python leg's log shows both installs and the rehearsals. Record each platform's added time from the job logs
  (`gh run view --job <id> --log`) in the PR description.
- [x] 6.5 Commit as `feat(installation): ...`. Verify: `uv run scripts/check.py` passes before the commit.

## 7. Runners' dependencies are licensed compatibly (design D11; spec: runner-protocol)

- [x] 7.1 Write the tests first, in `scripts/tests/`, with a fixture `uv.lock`, fixture distribution metadata and a
  fixture tree. They cover: MIT and BSD-3-Clause passing; `GPL-3.0-only` failing, naming the package, the runner, the
  licence and `scripts/licences.toml`; no licence failing; an `OR` expression with one branch on the list passing; a
  classifier mapped to SPDX; an unmapped classifier failing; workspace members skipped; today's plugins checking no
  package; and runner-protocol's weak-copyleft scenarios (`certifi` from PyPI passing, `certifi` from a git source or
  a `[tool.uv.sources]` override failing, and a tracked file carrying the MPL-2.0 notice failing). Verify: they fail
  before the script exists, run and shown.
- [x] 7.2 Add `scripts/runner_licences.py` and `scripts/licences.toml`, with the two tiers of D11 and D13: each
  licence with a one-line reason, and each weak-copyleft one with its notice text and a citation of the owner's
  comment. Run it from `scripts/check.py` with the bundle check, adding its paths to `scripts/check-paths.toml` as the
  bundle check's are. Verify: 7.1's tests pass, and `uv run scripts/check.py` passes and lists the licence check.
- [x] 7.3 Commit as `feat(scripts): ...`. Verify: `uv run scripts/check.py` passes before the commit.

## 8. The guarantees and how to add an extra, for runner authors (design D12; spec: runner-protocol)

- [ ] 8.1 Add a "Runners with client libraries" section to `contributing/runners.md`. It links to runner-protocol's
  requirements by name rather than restating them, says a library-backed runner's design names how it keeps each
  one, and lists the steps for adding an extra (D12), naming the check behind each. Link to it from the plugin
  section of the README, if there is one. Verify: each anchor resolves on the pushed branch (GitHub's rendered file
  view, grepping `user-content-<slug>`), and every check it names exists.
- [x] 8.2 Commit as `docs(runners): ...`. Verify: `uv run scripts/check.py` passes before the commit.

## 9. Integration

- [ ] 9.1 Run the full check (`uv run scripts/check.py`) and `openspec validate runner-extras --strict` on the
  branch's head. Verify: both pass, output shown.
- [ ] 9.2 Reply to the #291 session (track-b-11-291-troupe-lmstudio-runner). Say what #291's pull request adds once
  this merges: the plugin's dependency, the `lm-studio` extra and its `all` entry, `in_extra=True` in the table, the
  install page's list row, and the release exclusion while the plugin is bare. Verify: the message is sent and quoted
  in the PR description.

## Workflow follow-up

- Open a draft PR that closes #333, act on Claude's review of the last push, and mark it ready only once that review
  is clean. CI must pass on Linux, macOS and Windows.
- Archive the change on the branch before merging, and validate it strictly first.
- After the owner merges, comment on #333 with the PR and the archived change, and check the card is Done.
