# Proposal: theatre-template-and-guard-xdist

## Why

Two pieces of test tooling cost time and trust, from the timing spike of 2026-11-10/11 (`spike-test-time`, d55029d0).

- **troupe-run/troupe#362.** 668 tests run `git init` (711 inits) and then `add` and `commit` to build the same few
  theatre shapes. Building `test_run_workspaces.py`'s `committed()` theatre took 131 ms. Copying a built one with
  `shutil.copytree` took 27 ms. The estimate is ~70 s of worker time, or ~23 s (~5%) of the suite's wall time on 3
  workers.
- **troupe-run/troupe#365.** Running a hand-picked set of tests from several packages by node id reports `guard:`
  errors at teardown for tests that pass. Each error blames a test for reading another selected module's bytecode or
  source. That's how slow and flaky tests get timed and debugged, so a false error there either sends someone off to
  tag tests that don't need it, or teaches them to ignore the guard.

  The issue's guess was that a worker's collection imports are counted against "whichever test runs first", under
  xdist. Reproducing it on this branch showed something else. It happens in one process too (2 passed, 2 errors without
  `-n`), and every selected test is blamed for every other selected module. With a `file::test` argument, pytest's
  `Session.collect` imports each module while the Session's own collect report is being made. `guard_pytest` adds a
  read to every open window, so the Session's window (node id `""`) holds every module's imports. And every test's
  `listchain()` includes the Session, so every test inherits them. A run given paths, or no arguments, collects
  modules after the Session's report, which is why the full suite and per-package runs are clean.

## What Changes

- **A theatre built once, copied per test (#362).** The shared builders (`gitrepo.make_repo`, `runtesting.theatre`,
  `test_run_workspaces.committed` and `scripts/tests/conftest.py`'s `make_repo`) copy a template that each test
  process builds the first time a shape is asked for. Each test still gets its own repository and its own HOME, as
  now. A copy is made to look like a fresh build where git looks: new file times, and an index whose stat data matches
  the copied files.
- **Tests that depend on a fresh `init` keep building their own.** `test_git_state_cache.py` tests object timestamps,
  the index's stat data and the racy-git window on purpose, and keeps its own fixture. An audit of the other users of
  the builders finds any more, and each one asks for a fresh build by name.
- **The suite is measured before and after**, 3 xdist workers with a fresh `--basetemp`, interleaved with a baseline,
  and the numbers are recorded in the design and the pull request.
- **A test is blamed only for its own collection reads (#365).** `guard_pytest` counts a read made while a collector
  is being collected against that collector only, not against the collectors it's nested in. So the Session's window
  no longer holds the modules collected inside it, and a test's reads are its own module's and its own collectors'.
  `guard_pytest.py` is delivered from troupe-run/infrastructure (the guard's `delivered-file` rule refuses a change to
  it here), so the fix is an infrastructure pull request, delivered to troupe's `main` by the infrastructure App.
- **A troupe test shows it**: a selection of tests from two scopes, given by node id, passes with no guard errors in
  one process and across xdist workers, and a real untagged read in the same selection still fails.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `quality-check`: "Every test run keeps the declaration true" gains a scenario. A run that selects tests from several
  packages by node id fails a test only for what it reads itself, not for the other selected modules' imports.

The theatre template changes no requirement. It's how the tests build their repositories, and what each test sees
stays the same.

## Impact

- **Test helpers in troupe**: `packages/troupe/tests/gitrepo.py`, `runtesting.py`, `test_run_workspaces.py`,
  `scripts/tests/conftest.py`, and `pyproject.toml`'s `addopts` (to load the template plugin). The tests that call
  them don't change, apart from any the audit finds that need a fresh build.
- **`scripts/tests/test_guard_pytest_workers.py`** (troupe's own, not delivered) gains the cross-package selection
  test.
- **troupe-run/infrastructure**: `scripts/guard_pytest.py` and its tests, through an infrastructure issue and pull
  request. This change's pull request waits for the delivery to reach troupe's `main` and is rebased on it.
- **Not touched**: the git adapter and anything under `packages/*/src/`. Bundle 2 (troupe-run/troupe#367, git call
  speed) is changing the adapter at the same time. This change keeps to test fixtures and `guard_pytest`, and is
  rebased if #367 merges first.
- **Out of scope**: the git calls troupe itself makes during a test (#360, #361); `test_release_config.py`'s 32 s of
  fixture setup, which copies a workspace rather than building a theatre; `test_git_state_cache.py`'s own 24 s,
  which needs fresh builds by design.
