# Tasks

## 1. Baseline

- [x] 1.1 Record the baseline: `uv run scripts/check.py` on this machine, with the total and the tests gate's time.
  Verify by recording both times in this task. This is the "before" number for 3.4. Ask the owner before running it:
  it saturates the CPU for about four minutes
  - *Done without an extra run:* the planning commit (`35f7e85`) ran the full check through the guard, because no
    declaration existed yet. On this Mac: tests gate 220.9 s (1723 passed, 4 skipped), check 227 s in total.
- [x] 1.2 Check that `scripts` on pytest's `pythonpath` shadows nothing (design D4). No module named `check`,
  `guard`, `guard_pytest`, `on`, `python_versions` or `release_config` exists under any `testpaths` directory or
  `packages/troupe/tests`. Verify with a `git ls-files` search, and record the result here
  - *Result:* `git ls-files | grep -E '(^|/)(check|guard|guard_pytest|on|python_versions|release_config)(\.py|/__init__\.py)$'`
    finds only the six files in `scripts/`, so nothing is shadowed.

## 2. `check.py --scope`

- [x] 2.1 Write `scripts/tests/test_check_scope.py` first, in `test_check_activation.py`'s style, each test named
  for what its body asserts. Cover:
  - `requested_scopes` sorts and deduplicates (`["docs", "docs"]` gives `("docs",)`);
  - an undeclared scope exits naming the scope and `scripts/check-paths.toml`;
  - no declaration at all, with `--scope docs`, exits the same way;
  - a malformed declaration exits with the guard's message, and no gate runs;
  - `gates(())`'s pytest command has no `-m`, and `gates(("docs",))` has `-m docs`;
  - `run_gates` with a stand-in tests gate that exits 5 passes in a scoped run, printing that nothing was tagged,
    and fails in an unscoped one;
  - a failing gate stops the run and names itself, scoped or not.

  Use temporary directories and small `python -c` commands as stand-in gates, not the real suite. Verify the tests
  fail before 2.2 for the right reason
- [x] 2.2 Change `scripts/check.py` to infrastructure's reference shape (design D1): `argparse` with
  `--scope action="append"`, `requested_scopes`, `gates(scopes)`, `run_gates` with `NO_TESTS_RAN`, and `import guard`
  at the top. Update the module docstring's usage line. Verify 2.1's tests and `test_check_activation.py` pass, and
  that `uv run scripts/check.py --scope nope` exits before printing `==> ruff lint` (spec: an undeclared scope is
  refused before any gate runs)

## 3. The declaration, the plugin and the tags

- [x] 3.1 Add `scripts/check-paths.toml`: `version = 1`, `[skip] paths = ["openspec/**"]`, and
  `[scopes.docs] paths = ["docs/**", "plugins/runner-scripted/README.md"]`. Give each group a comment saying why
  it's safe, and that a `docs` test must read in-process or be tagged by hand (design, Risks). Verify
  `uv run --no-project python -c "import sys; sys.path.insert(0,'scripts'); import guard, pathlib; print(guard.check_paths(pathlib.Path('scripts/check-paths.toml').read_text()))"`
  parses it
  - *Result:* `CheckPaths(skip=('openspec/**',), scopes=(('docs', ('docs/**', 'plugins/runner-scripted/README.md')),))`
- [x] 3.2 Load the plugin (design D4): add `"scripts"` to `pythonpath` and `"-p", "guard_pytest"` to `addopts` in
  the root `pyproject.toml`. Run the full suite with no tags yet (design D3). Verify that the failures are exactly
  the tests that read `docs/**` untagged, and that none reads `openspec/`. Record the failing tests here, and compare
  them with the design's expected list
  - *Result:* `uv run pytest` with the plugin loaded and no tags gave 1737 passed, 4 skipped and 26 errors, in
    218.7 s. Each error was the plugin's teardown failure for a `docs` read, by module: `test_cli_docs` 5,
    `test_event_store_doc` 5, `test_exit_codes_doc` 1, `test_platform_docs` 2, `test_runners_doc` 5, `test_runs_doc`
    7, and `test_scripted_schemas.py::test_the_readmes_options_table_lists_exactly_the_options_schemas_properties`.
    That's exactly the design's expected list, with nothing more. No message mentions `openspec`. Each of the six
    modules collects exactly as many tests as it had errors, so every test in them reads the docs, and a
    module-level tag fits (design D2).
- [x] 3.3 Tag what 3.2 found (design D2): `pytestmark = pytest.mark.docs` on the six doc modules, and
  `@pytest.mark.docs` on
  `test_the_readmes_options_table_lists_exactly_the_options_schemas_properties`, plus anything else 3.2 found.
  Verify that the full `uv run scripts/check.py` passes, and that `uv run scripts/check.py --scope docs` runs every
  gate and only the tagged tests. Record the test count and time of each
  - *Scoped:* `uv run scripts/check.py --scope docs` ran ruff lint, ruff format, mypy, the import contracts and
    tests. The tests gate collected 1741, deselected 1715 and passed 26, in 1.0 s, and the whole check took 1.55 s.
  - *Full:* the guard's full check on `0cf12be`, which staged the declaration and so ran everything, with the
    plugin and tags: every gate passed, and the tests gave 1737 passed, 4 skipped in 224.0 s (225 s in total).
- [x] 3.4 Measure the plugin's cost. Time the full suite on the same machine as 1.1, with the plugin. Verify that
  the difference from 1.1 is recorded here, and that it's under about 5% (design, Risks). If it isn't, stop and
  raise it in troupe-run/infrastructure
  - *Full suite:* with the plugin (3.2's untagged run), 218.7 s. Without it, 220.9 s (1.1) and 207.1 s (the
    group 2 commit). The run-to-run spread without the plugin, about 7%, is larger than the threshold. So it was also
    measured directly:
  - *Controlled:* the store-text and vcs-git suites (127 tests, file-heavy), run back to back, alternating. With
    the plugin they took 60.1 s and 64.1 s; without it (`-o addopts=...` minus `-p guard_pytest`), 67.6 s and
    62.4 s. There's no measurable cost: the noise is larger than any difference.
- [x] 3.5 Prove the tag check catches drift (spec: every test run keeps the declaration true). Temporarily remove
  the `docs` tag from one doc module and run that module. Verify that it fails, naming the test, the docs file and
  the `docs` tag. Restore the tag, and don't commit the removal. Record the message here
  - *Result:* with `pytestmark` removed from `test_exit_codes_doc.py`, its test ran with 1 passed and 1 error:
    `guard: packages/troupe/tests/test_exit_codes_doc.py::test_exit_code_document_lists_exactly_the_codes_in_the_enum
    reads docs/cli/exit-codes.md, which scripts/check-paths.toml puts in scope `docs`, so a change to it wouldn't run
    this test. Tag the test `docs` (pytest: @pytest.mark.<name>).` The tag was restored from a copy, and
    `git diff` shows only the intended tagging.

## 4. Docs

- [x] 4.1 Update the README's Development section. Say that a commit runs only what its staged paths need, by
  `scripts/check-paths.toml`: nothing for `openspec/` alone, the doc tests for docs alone, everything otherwise. Say
  how to run a scope by hand (`uv run scripts/check.py --scope docs`), and that every test run checks the tags.
  Verify that the commands run as written
  - *Result:* `uv run scripts/check.py --scope docs`, as written in the README: every gate passed, and the tests
    gave 26 passed, 1715 deselected.

## 5. Evidence on real commits

- [x] 5.1 Once 3.1 is committed, commit a task tick that stages only this change's `tasks.md`. Verify that the guard
  prints that the check is skipped, naming `openspec/**` and `scripts/check-paths.toml`. Record the output here
  (design D5)
  - *Result:* `90424ec`, which staged only `tasks.md`, printed `guard: only openspec/** is staged; the check is
    skipped (scripts/check-paths.toml).` The commit took 0.45 s, against 218 to 227 s for this branch's full checks.
- [x] 5.2 Commit a change that stages only files under `docs/` (or the scripted runner's README). It needs a real
  docs edit; don't make one up. If the change has none by then, demonstrate it in a scratch clone instead. Verify
  that the guard runs `scripts/check.py --scope docs`, and that it passes. Record the output and time here
  - *Result (scratch clone):* this change has no real `docs/` edit, so it was shown in a throwaway clone of this
    branch at `8feacfe`, with hooks on, by appending a line to `docs/platform.md`. Nothing was pushed, and the clone
    was deleted. The guard printed `guard: only docs/** is staged; running scripts/check.py --scope docs instead of
    the full check (scripts/check-paths.toml; gives up after 600s)...`. Every gate ran, and the tests collected 1741,
    deselected 1715 and passed 26. Then: `guard: scripts/check.py --scope docs passed in 11s.` That's in a fresh
    clone, with mypy's cache cold. The warm run in 3.3 took 1.55 s.
- [x] 5.3 Open the PR with `Closes #108`. Verify that all six CI jobs pass with the plugin loaded (design, Risks: the
  plugin's first runs on macOS and Windows), and record the run here
  - *Result:* PR #111, run 38736541308. All six `check` jobs passed with the plugin loaded: ubuntu 3.12 3m16s,
    ubuntu 3.13 3m10s, macos 3.12 5m24s, macos 3.13 5m25s, windows 3.12 6m40s, windows 3.13 6m22s. `guard` and DCO
    passed too.
  - *Rebased onto `main` at `20e8cd0` (Python 3.14 and 3.15, widened bound), after the run above.* The rebase was
    clean. The commit ids above are the rebased ones, but the timings were measured on the same commits before the
    rebase, which differ only by main's changes. The rebase doesn't run the hook, so the combination was
    checked separately. `uv run scripts/on.py <v> scripts/check.py --scope docs` passed on 3.12, 3.14 and 3.15
    (26 tests each), and `scripts/tests` passed on each (78 tests). With the tag removed from
    `test_exit_codes_doc.py`, the plugin failed that test on 3.14 and 3.15, as it does on 3.12. CI's matrix is now
    12 jobs, and its run on the rebased branch is recorded below.
  - *Result after the rebase:* run 38739097317 on `55061d0`. Eleven of the 12 `check` jobs passed first time.
    `check (windows-latest, Python 3.14)` failed in
    `test_platform_watching.py::test_a_wait_with_nothing_changing_returns_after_its_timeout_saying_nothing_changed`:
    a 0.5 s wait measured 0.4999561 s by `time.monotonic()`. That's a Windows clock-skew flake in code this change
    doesn't touch, filed as #112. On re-run that job passed (job 116442967506). All 15 checks are green: 12 `check`,
    2 `guard` and DCO.

## Workflow follow-up

- Archive the change on the branch (`/opsx:archive`) before merging. The archive commit should itself show the
  skip.
- After the merge, comment on #108 with the PR and the archived change. Check that #108 is closed and its card says
  Done. Then tell #101 and #109 that troupe's declaration is in place.
