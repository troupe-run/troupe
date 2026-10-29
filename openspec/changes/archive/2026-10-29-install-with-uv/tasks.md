# Tasks

## 1. The bundle package (design D1, D2, D6)

- [x] 1.1 Write the bundle's contents tests first, in `scripts/tests/workspace/test_bundle.py`. Each test's name says
  exactly what it checks:
  - `troupe-run`'s dependencies are exactly `troupe` plus every other workspace member, read from the root
    `pyproject.toml`'s member globs. The failure names each missing or extra name and `packages/troupe-run/pyproject.toml`.
  - core's dependencies name no workspace member. The failure names it, the file, and `troupe-run` as where it belongs.
  - the bundle's `troupe` script target equals core's, naming both when they differ.

  Verify: run `uv run pytest scripts/tests/workspace/test_bundle.py` and see it fail, because `packages/troupe-run/`
  doesn't exist yet.
- [x] 1.2 Create `packages/troupe-run/`:
  - `pyproject.toml`: `troupe-run`, `0.0.1.dev0`, the shared `requires-python`, the dependencies from D1 by bare
    name, `troupe = "troupe.cli:main"`, `uv_build` as core's;
  - `LICENSE` (copied);
  - a `README.md` that says what the bundle is for and gives the install command;
  - `src/troupe_run/__init__.py`, holding only a docstring.

  Verify: `uv sync` succeeds, and the 1.1 tests pass. Adding a scratch member under `packages/` without the
  dependency fails the first test, naming it. Listing `troupe-vcs-git` in core's dependencies fails the second test.
  Both scratch changes are then removed.
- [x] 1.3 Wire the member in:
  - the root `pyproject.toml`'s `[tool.uv.sources]`, plus the tool lists that name every package (ruff `src`, mypy
    `files` and `mypy_path`, import-linter `root_packages`);
  - `release-please-config.json` and its `troupe` linked group, with the `uv.lock` extra-file as the others have;
  - `.release-please-manifest.json` at `"0.0.0"`;
  - a `run` scope in `scripts/check-paths.toml` (the reach tool's name for `troupe-run`), with the tests
    `uv run scripts/check_paths_reach.py` prints;
  - `docs/backstage/changelog.md`, which lists its changelog under troupe.

  Verify: `uv run scripts/check.py` passes, including the release configuration's, Python bounds' and path scopes'
  checks, and the changelog page's check.

## 2. The install check (design D3, D4)

- [x] 2.1 Write `scripts/install_check.py`: the command template and the repository URL as named constants, the
  `--ref` and `--python` options, the steps in D4, and named timeouts. Each failure names the step, the command and its
  output. Add tests in `scripts/tests/workspace/` (the script names the bundle's path) for what can be checked
  without installing: the command it builds for a given ref and Python, that a ref that isn't a commit is refused by
  name, and that the tool directories are temporary and removed afterwards.

  Verify: the tests pass. `uv run scripts/install_check.py` on this branch's `HEAD` installs, prints the version,
  and reports a succeeded scripted run. Afterwards, `uv tool list` and the developer's path are unchanged.
- [x] 2.2 Show that the check catches a broken install: in a scratch commit, remove `troupe-runner-scripted` from the
  bundle's dependencies, run the install check against that commit, and see it fail, naming the step. Then drop the
  scratch commit. Record the output in the PR description. (Done in a throwaway clone. It fails at "define the
  actor", one step before perform: `troupe config set` checks the options against the runner's published schema,
  and names the missing `troupe_runner_scripted`.)

## 3. CI (design D5)

- [x] 3.1 Add the install-check step to `check-legs` in `.github/workflows/ci.yml`, after "Check", only when `check-args`
  is empty. Pass `--ref ${{ github.sha }}` and `--python ${{ matrix.python }}`, with each OS's own shell, as the Check
  step does. Extend `scripts/tests/test_ci_workflow.py` so that removing the step, or running it on a scoped check,
  fails a test.

  Verify: the workflow tests pass. On the pull request, every leg (3 OSes × 4 Pythons) runs the step and passes. Read
  how long the step took from each job's log. If the shallow checkout can't serve the commit, apply D5's fallback and
  record it in design.md.

## 4. The docs (design D3, D7, D8)

- [x] 4.1 Write the docs test from D3 (tagged `docs`): every `uv tool install` line in `README.md` and under `docs/`
  matches `scripts/install_check.py`'s template, with its repository URL and a documented ref. The failure names the
  page, the line and the expected command. Verify: a scratch copy with `#subdirectory=packages/troupe` fails, naming
  the page and line, and the scratch copy is then removed.
- [x] 4.2 Check whether `uv tool upgrade troupe-run` fetches a newer `main`: install from a scratch commit, add a commit,
  upgrade, and compare `troupe --version` or the installed commit. Record the answer in design.md D7.
- [x] 4.3 Rewrite the README's opening paragraph and add an **Install** section, and rewrite
  `docs/opening-night/install.md`, as D7 says, using 4.2's answer for upgrading. Name the Python bound, and extend the
  existing Python-versions check if it reads the README's bound, so the install page is checked too. Verify: the
  docs check and the 4.1 test pass. Following the page by hand in a new shell, using the same temporary
  `UV_TOOL_DIR`/`UV_TOOL_BIN_DIR` as the install check, gives a `troupe` that prints its version.
- [x] 4.4 Re-read #62, #124, #126, #145, #146, #147 and #148, then make D8's edits to the six pages. Pages stay
  `prerelease: true`. Verify: `uv run scripts/check.py --scope docs` passes, and `grep -rn '#62\|#124' docs` shows
  only the links D8 keeps or changes.

## 5. Integration

- [x] 5.1 Run `uv run scripts/check.py` (the full check) and `uv run scripts/install_check.py` on the final commit.
  Both pass, and every CI leg on the pull request is green, the install step included.

## Workflow follow-up

- Open the PR with `Closes #144`. Its description says that installing by tag, part of #144's "Done when", moved to
  #189 at the owner's request (2026-10-29), and includes 2.2's output.
- Act on Claude's review of the last push, archive the change on the branch, and queue the merge.
- After the merge, comment on #144 with the PR and the archived change, and check that #144 is closed and its card is
  Done.
