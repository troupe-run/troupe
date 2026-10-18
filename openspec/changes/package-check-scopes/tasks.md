# Tasks

## 1. Reach analysis (needs nothing from infrastructure)

- [x] 1.1 Write `scripts/check_paths_reach.py` (design D3): suites from `testpaths`, a suite's code and helpers through
  `pythonpath`, `ast` imports anywhere in a module mapped to workspace packages by `src/<module>`, package sources and
  `pyproject.toml` workspace dependencies followed transitively. Verify with unit tests in
  `scripts/tests/test_check_paths_reach.py` on small temporary workspaces: a function-level import counts, a
  `TYPE_CHECKING` import counts, a transitive dependency counts, a helper's import counts for the suite that imports it.
- [x] 1.2 Add the entry-point rule: each loader module's group, each package's registered groups from its
  `pyproject.toml`, and a suite reaching a loader through core's module-level import closure reaching every package in
  that group. Fail, naming the file and line, when any workspace source calls `entry_points(` outside a known loader.
  Verify with temporary-workspace tests for both, and that the real tree's five loaders are found.
- [x] 1.3 Add named reach (string literals naming a package directory, module, or `plugins`/`packages` as a path
  segment) and the `scripts` rule, with the four full-check files left out. Verify with temporary-workspace tests,
  including a subprocess command `[sys.executable, "-m", "<module>"]` and a `ROOT / "plugins"` glob.
- [x] 1.4 Run the analysis on the real tree and compare it with the projected map in design.md. Record every
  difference in design.md with its cause (expected: only imports inside functions widening it). Verify by pasting the
  table the analysis prints.
- [x] 1.5 Test the comparison against a declaration: equal passes; a missing suite and an extra suite each fail with a
  message naming the scope, the suite and the `tests = [...]` line to paste; a scope with no `tests` is reported the
  same way. Verify with tests on parsed in-memory declarations (no `tests` key needed in the real file yet).
- [x] 1.6 Run `uv run scripts/check.py` and commit (`feat(scripts): compute each test suite's reach`).

## 2. The `tests` key (troupe-run/infrastructure#86)

- [x] 2.1 Confirm #86 is merged and delivered to troupe (a `chore(guard): deliver` commit on `main`), and rebase this
  branch onto it. Verify: `guard.check_paths` accepts a `tests` key and `guard_pytest` applies it, by reading the
  delivered files and the archived infrastructure design.
- [x] 2.2 If #86's final shape differs from design D2 (entry form, version, how an unmatched entry is reported),
  update design.md and the spec delta before going on, and say so in the commit.

## 3. The scopes

- [x] 3.1 Add the seven package scopes and `scripts` to `scripts/check-paths.toml` (design D1), with `tests` set from
  the analysis's table and a comment on each saying what reaches it. Verify with `uv run scripts/guard.py check-scope`
  (or `guard.check_scope`) for: a stage-local file (`stage_local`), a vcs-git plus store-text pair (both), a
  `scripts/on.py` change (`scripts`), `scripts/check.py` (full), a core file (full), a package's
  `pyproject.toml` (full), a new `scripts/new.py` (full),
  `plugins/runner-scripted/README.md` (`docs` and `runner_scripted`).
- [x] 3.2 Make the reach test compare the real declaration and give its module the `pytestmark` built from the
  declaration (design D4). Verify: it passes on the real tree; a full run shows no `guard_pytest` violations; and,
  temporarily, removing one suite from one scope's `tests` fails it with the expected message (record the output,
  then restore).
- [x] 3.3 Check each scope's selection: `uv run pytest -m <scope> --collect-only -q` for every scope, and confirm the
  collected directories are exactly the scope's `tests` plus the reach test. Record the counts.
- [x] 3.4 Re-measure: one serial run with `--junitxml`, summed per suite, and each scope's test time from it. Replace
  the projected tables in design.md with the measured ones. Ask the owner before running it if the machine is busy.
- [x] 3.5 Run the full check and commit the declaration (`feat(check): scope each package's tests to the suites that
  reach it`); the guard runs the full check because the declaration is staged.
- [x] 3.6 Update the header comment in `check-paths.toml`, and any mention of the declaration in `docs/` or the README
  that names only `docs` and `openspec/**` (search for `check-paths`). Verify the `docs` tests pass.

## 4. Proved on real commits

- [ ] 4.1 A commit staging only `scripts/` files (not the four full-check files), such as a docstring fix found in 1.x,
  shows the guard running `--scope scripts` and only the scripts suite. Record the guard's line and the test count.
- [ ] 4.2 A commit staging only one leaf package's files shows the guard running that package's scope and the suites
  the table names. Record the guard's line and the collected suites. If no real change to a leaf package is due, ask
  the owner which change to use rather than making one up.
- [ ] 4.3 Open the PR (`Closes #109`) and confirm every CI job passes on Linux, macOS and Windows.

## Workflow follow-up

- Archive the change on the branch before merging (`/opsx:archive`).
- After the merge: comment on #109 with the PR and the archived change, check it's closed and its card is Done.
