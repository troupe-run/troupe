# Tasks

The tests of parallel behaviour run real pytest under xdist on small files written into a temporary directory
(pytester), not hand-built reports. That way each fixture is the shape xdist actually produces. None of these tasks
runs a repeated or load-heavy local loop without asking the owner first. The repeated runs are CI's (design D7).

## 1. Dependency and the "before" numbers

- [x] 1.1 Add pytest-xdist to the root dev group (`uv add --dev pytest-xdist`), at the newest release at least two weeks
  old. Verify `uv sync --locked` succeeds, `uv run pytest --version` lists xdist among the plugins, and a plain
  `uv run pytest scripts/tests/test_check_scope.py` still runs in one process (no `created: N workers` line)
- [x] 1.2 Record the "before" check-step times: with `gh api`, read the check step's duration for each job of the most
  recent 10 successful CI runs on `main`, and group them per platform (min, median, max). Time one local
  `uv run scripts/check.py` on macOS. Save the table and the query in the change's `timings.md`, for the PR
  (design D7). Verify the table has all three platforms and names the runs it came from

## 2. The protocol guard checks once, across workers (spec: quality-check; design D4)

- [x] 2.1 In `protocol_guard.py`: on a worker, `pytest_sessionfinish` puts the sorted codes it saw into
  `config.workeroutput` and doesn't check. On the controller, an `optionalhook` `pytest_testnodedown` merges each
  worker's codes into `_seen`, and records a worker that sent none. The controller's check fails the run, naming the
  worker, when a worker reported nothing and the exit status is otherwise OK. It's unchanged otherwise. Verify mypy
  and ruff are clean, and the module docstring says how the tally crosses workers
- [x] 2.2 Add tests in `packages/troupe/tests/` with pytester (`-p pytester`, loading `protocol_guard` the way
  `addopts` does). (a) A full run under `-n 2`, whose tests raise no codes, fails once, naming the unexercised codes in
  one line, not once per worker. (b) The same run with `-k` passes, with no line about unexercised codes. (c) The same
  run without `-n` fails the same way as (a), so the one-process path is unchanged. Verify (a) fails when the workers
  check for themselves (2.1's worker branch removed), 2.3's split-codes test fails when the controller doesn't merge,
  and all pass with 2.1
- [x] 2.3 Add a test of the merge on its own. Codes split across two workers' outputs (none of them holding all) leave
  nothing unexercised, and a worker whose output lacks the key is reported by name. Verify it with the hook functions
  called on stand-in nodes carrying real `workeroutput` dicts, and check that the test's name says exactly that
- [x] 2.4 Verify the real suite under `uv run pytest -n auto --dist worksteal` (one run) passes the protocol guard's
  full-run check. A broken union would fail it, naming codes that were in fact raised

## 3. The commit guard's tag rule holds in a parallel run (spec: quality-check; design D5)

- [x] 3.1 Add a pytester test in `scripts/tests/`. In a temporary directory with a `scripts/check-paths.toml` that
  declares a `docs` scope over `docs/**` and a `docs/x.md`, a run with `-n 2 -p guard_pytest` fails the test that reads
  `docs/x.md` untagged (its report names the test, `docs/x.md` and the `docs` tag), and passes the tagged test that
  reads it. Add a second case that reads a file under `openspec/`. Verify the same file run without `-n` gives the same
  outcomes
- [x] 3.2 If 3.1 shows `guard_pytest` doesn't hold under xdist, stop. Open an issue in troupe-run/infrastructure (on
  the roadmap board) with the pytester reproduction, and wait for the fix to be delivered. Don't edit the copy here.
  Verify by the delivered `guard_pytest.py` passing 3.1. (Skip, and say so, if 3.1 passes on first run.)
  Not needed: 3.1 passed on its first run against the delivered `guard_pytest.py`. The guard fails a test in its
  teardown report, which pytest counts as an error, in one process and across workers alike

## 4. `check.py` runs the tests in parallel (spec: quality-check; design D1, D2, D3)

- [x] 4.1 In `gates()`, add `-n auto --dist worksteal` to the tests command, before any `-m`. Update the module
  docstring to say the tests run in parallel and that `PYTEST_XDIST_AUTO_NUM_WORKERS` sets the worker count. Verify
  that `uv run scripts/check.py` prints xdist's worker line and passes
- [x] 4.2 Update `scripts/tests/test_check_scope.py`. The full tests command carries `-n auto --dist worksteal`, and
  the scoped command is still exactly the full command plus `-m <expression>`. Rename any test whose name no longer
  matches what it asserts. Verify the tests fail with 4.1 reverted, and pass with it
- [x] 4.3 Add a test that `pyproject.toml`'s pytest `addopts` turns on no xdist option (`-n`, `--numprocesses`,
  `--dist`), named for that, so running pytest directly stays one process (spec: "Running pytest directly stays one
  process"). Verify it fails when `-n auto` is added to `addopts`
- [x] 4.4 Add pytester tests of the tests command's behaviour under xdist, which `run_gates` relies on. A run with
  `-n 2 -m <unused marker>` exits `NO_TESTS_RAN` (5). A run with one failing test among passing ones exits 1, and its
  summary names the failing test. Then `run_gates` given a tests step that exits 5 in a scoped check passes, and says
  nothing was tagged, as it already does in one process. Verify each case against real xdist runs
- [x] 4.5 Document it in `README.md` next to the description of the gates: the tests run in parallel, one worker per
  CPU, `PYTEST_XDIST_AUTO_NUM_WORKERS` changes the count, and plain `uv run pytest ...` stays one process for
  debugging. Verify `uv run scripts/check.py --scope docs` passes (the README isn't in the docs scope, so also run the
  full check)

## 5. Shared state, and the time it saves (spec: quality-check; design D6, D7)

- [x] 5.1 Run `uv run scripts/check.py` locally once, in parallel. Fix every test that fails only in parallel at its
  cause (its own `tmp_path`, `monkeypatch`, or a timing bound that holds under load), each in its own commit that names
  the shared state. Verify by the next full parallel run passing, and `git status` showing no file the run created
  outside ignored paths
- [x] 5.2 Confirm from hypothesis's documentation that `DirectoryBasedExampleDatabase` is safe for several processes
  sharing one directory, and cite the passage in design D6. If it isn't, give each worker its own database directory
  under `.hypothesis/` in `hypothesis_profiles.py`, with a test. Verify by the citation, or by the test.
  Done: the documentation is silent on concurrent processes, so D6 cites the source instead (atomic rename on save,
  tolerant fetch and delete) and the fact that xdist runs each test in exactly one worker. The database stays shared
- [ ] 5.3 Time `uv run scripts/check.py --scope docs` in parallel and in one process (one run each, macOS). If parallel
  is clearly slower, update design D1 and the spec before changing `gates()` (design Risks). Verify the two timings are
  in the scratch notes, with the decision
- [x] 5.4 If any test can't share the machine honestly, stop and update the design (D6) and the spec before code
  depends on it. Verify by the design naming each such test and why, or by 5.1 to 5.3 finding none

## 6. Verification on CI (spec: quality-check; design D7)

- [ ] 6.1 Push the branch, open the PR (`Closes #83`), and get CI to pass on all 12 jobs five times. That means the
  first run, then four re-runs of the whole workflow (`gh run rerun <id>`). Any failure is fixed per design D6, and the
  count starts again. Verify by listing the five run ids with every job green
- [ ] 6.2 Read the "after" check-step times from the five runs with the same `gh api` query as 1.2, and add the
  before/after table per platform, with the local macOS times, to the PR description. Verify the PR shows both columns
  for Ubuntu, macOS and Windows

## Workflow follow-up

- Run `/opsx:archive` on the branch before merging, so the PR lands code, tests and specs together.
- After the merge, check #83 is closed and its card on the troupe roadmap board says Done. Comment on #83 with the PR
  and the archived change.
- Note on #84 that the longest single test now sets the floor for the suite's wall time.
