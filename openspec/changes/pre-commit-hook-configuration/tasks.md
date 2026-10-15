# Tasks

## 1. Baseline

- [x] 1.1 Record the baseline: `uv run scripts/check.py` on this machine, with the total and the tests gate's time.
  Verify by recording both times in this task. This is the "before" number for 3.4. Ask the owner before running it:
  it saturates the CPU for about four minutes
  - *Done without an extra run:* the planning commit (`134732b`) ran the full check through the guard, because no
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

- [ ] 3.1 Add `scripts/check-paths.toml`: `version = 1`, `[skip] paths = ["openspec/**"]`, and
  `[scopes.docs] paths = ["docs/**", "plugins/runner-scripted/README.md"]`. Give each group a comment saying why
  it's safe, and that a `docs` test must read in-process or be tagged by hand (design, Risks). Verify
  `uv run --no-project python -c "import sys; sys.path.insert(0,'scripts'); import guard, pathlib; print(guard.check_paths(pathlib.Path('scripts/check-paths.toml').read_text()))"`
  parses it
- [ ] 3.2 Load the plugin (design D4): add `"scripts"` to `pythonpath` and `"-p", "guard_pytest"` to `addopts` in
  the root `pyproject.toml`. Run the full suite with no tags yet (design D3). Verify that the failures are exactly
  the tests that read `docs/**` untagged, and that none reads `openspec/`. Record the failing tests here, and compare
  them with the design's expected list
- [ ] 3.3 Tag what 3.2 found (design D2): `pytestmark = pytest.mark.docs` on the six doc modules, and
  `@pytest.mark.docs` on
  `test_the_readmes_options_table_lists_exactly_the_options_schemas_properties`, plus anything else 3.2 found.
  Verify that the full `uv run scripts/check.py` passes, and that `uv run scripts/check.py --scope docs` runs every
  gate and only the tagged tests. Record the test count and time of each
- [ ] 3.4 Measure the plugin's cost. Time the full suite on the same machine as 1.1, with the plugin. Verify that
  the difference from 1.1 is recorded here, and that it's under about 5% (design, Risks). If it isn't, stop and
  raise it in troupe-run/infrastructure
- [ ] 3.5 Prove the tag check catches drift (spec: every test run keeps the declaration true). Temporarily remove
  the `docs` tag from one doc module and run that module. Verify that it fails, naming the test, the docs file and
  the `docs` tag. Restore the tag, and don't commit the removal. Record the message here

## 4. Docs

- [ ] 4.1 Update the README's Development section. Say that a commit runs only what its staged paths need, by
  `scripts/check-paths.toml`: nothing for `openspec/` alone, the doc tests for docs alone, everything otherwise. Say
  how to run a scope by hand (`uv run scripts/check.py --scope docs`), and that every test run checks the tags.
  Verify that the commands run as written

## 5. Evidence on real commits

- [ ] 5.1 Once 3.1 is committed, commit a task tick that stages only this change's `tasks.md`. Verify that the guard
  prints that the check is skipped, naming `openspec/**` and `scripts/check-paths.toml`. Record the output here
  (design D5)
- [ ] 5.2 Commit a change that stages only files under `docs/` (or the scripted runner's README). It needs a real
  docs edit; don't make one up. If the change has none by then, demonstrate it in a scratch clone instead. Verify
  that the guard runs `scripts/check.py --scope docs`, and that it passes. Record the output and time here
- [ ] 5.3 Open the PR with `Closes #108`. Verify that all six CI jobs pass with the plugin loaded (design, Risks: the
  plugin's first runs on macOS and Windows), and record the run here

## Workflow follow-up

- Archive the change on the branch (`/opsx:archive`) before merging. The archive commit should itself show the
  skip.
- After the merge, comment on #108 with the PR and the archived change. Check that #108 is closed and its card says
  Done. Then tell #101 and #109 that troupe's declaration is in place.
