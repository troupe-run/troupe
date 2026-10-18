# Design

## Context

See proposal.md for why, and the quality-check delta for what. What exists today:

- **`scripts/check.py`** runs five gates in order. The tests gate is `pytest`, plus `-m <expression>` for a scoped
  check. A scoped run that selects nothing exits 5 (`NO_TESTS_RAN`), which the script treats as a pass and says so.
  `scripts/tests/test_check_scope.py` checks the gate's command shape: the scoped command is the full command plus
  `-m`.
- **Three pytest plugins load for every run** through `addopts`:
  - `protocol_guard` wraps the error, notice and event-store classes in `pytest_configure` to validate details as
    they're built. It records each code troupe's own source constructs in a module-level set, `_seen`. At the end of
    a full run, `pytest_sessionfinish` fails the session if a catalogued code isn't in `_seen` (strict-schemas design).
    Its `unchecked()` switch is a module-level flag.
  - `guard_pytest` (delivered from troupe-run/infrastructure; not edited here) adds an audit hook per process and
    records the reads of each collector, fixture and test in module-level dicts. It fails a test at teardown by
    rewriting that test's report.
  - `hypothesis_profiles` re-registers the `default` profile without a deadline. CI sets `CI`, so hypothesis uses its
    `ci` profile there: fixed seeds, no example database. Local runs use `.hypothesis/` in the repository.
- **Tests isolate themselves** with `tmp_path` and `monkeypatch` (environment, `chdir`), and `gitrepo.py` gives each
  repository its own `HOME`. A search for `Path.home`, `gettempdir`, `os.environ[...] =`, `chdir`, sockets and
  session- or module-scoped fixtures found no writes outside `tmp_path`. The only module-scoped fixture is in
  `scripts/tests/test_flake_campaign.py`. troupe uses no sockets, so the macOS 104-byte socket-path limit doesn't apply.
- **The flake hunt** runs `python -m pytest` itself, with its own workers and rounds. It doesn't go through
  `check.py`.
- **CI** runs `uv run scripts/check.py` on 12 jobs: Ubuntu, macOS and Windows, each on Python 3.12 to 3.15.

## Goals / Non-Goals

**Goals:**
- One switch, in one place, that every local run, commit and CI job goes through.
- The guards keep their meaning in a parallel run: a code nobody raised still fails a full run, and an untagged docs
  read still fails its test.
- No test passes only because of the order it runs in, or because it ran alone.

**Non-Goals:**
- Shortening individual tests (#84). After this change the longest single test sets the floor for the suite's wall
  time, so #84 matters more, but it's a separate issue.
- Parallel rounds inside the flake hunt. It already overlaps whole pytest processes, and its evidence format (one
  JUnit report per round) would need rework.
- Changing CI's matrix or timeout.

## Decisions

### D1: The switch lives in `check.py`, not in pytest's `addopts`

`gates()` adds `-n auto --dist worksteal` to the tests command, before any `-m`. The scoped command stays "the full
command plus `-m`", so the existing shape test still says something true.

- **Alternative: `addopts` in `pyproject.toml`.** Every `pytest` would go parallel, including a developer running one
  test. That pays a few seconds of worker start-up for nothing and makes `pdb` and `-s` awkward. It would also put
  xdist inside the flake hunt's rounds, which already run several at once, and inside any pytester runs. #83 asks for
  `check.py`, and check.py is the path every gate run already takes.

### D2: Worker count is xdist's `auto`, with xdist's own override

`-n auto` starts one worker per CPU the process may use (xdist reads the affinity mask where the OS has one).
GitHub's runners give 3 to 4. A person who wants a different count sets `PYTEST_XDIST_AUTO_NUM_WORKERS`, xdist's own
variable, which `auto` honours. That gives one documented place, and no new troupe setting.

- **Alternative: oversubscribe (`-n 2x`),** since the tests mostly wait. It might be faster, but it loads the machine
  harder, and that's where timing tests flake. Start with `auto`. Tasks measure `auto` on CI. Changing the count
  later is a one-line edit, with its own measurement.
- **Alternative: a fixed count.** It's wrong on every machine but one.

### D3: Distribution is work-stealing

`--dist worksteal` hands out tests in chunks, and an idle worker takes work from a busy one. Durations here are very
uneven: one hypothesis state machine takes ~21 s, while most tests take milliseconds. Work-stealing is xdist's mode for
that.

- **Alternative: `load` (the default).** It pre-assigns tests round-robin, so a worker holding several slow tests
  becomes the tail.
- **Alternative: `loadfile`.** It keeps each file on one worker. The six slowest files are 64% of the time, so each
  would pin a worker for 12 to 31 s.
- **Alternative: `loadgroup`.** It's only needed for serial groups, and D6 says there are none.

### D4: The protocol guard tallies on the workers and checks once, on the controller

On a worker (`config` has `workerinput`), `pytest_sessionfinish` doesn't check. It puts the codes it saw, sorted, into
`config.workeroutput`. On the controller, an `optionalhook` implementation of xdist's `pytest_testnodedown` merges
each worker's codes into `_seen`. The controller's own `pytest_sessionfinish` runs after every node is down and does
the existing check, unchanged. In one process, without xdist, nothing changes: the optional hook is never called, and
the check reads the set the tests filled.

- A worker that ends without reporting its codes (it crashed, or was replaced) while the run's exit status is still
  OK is an error, named in the output and failing the run. Without it the union would be short, and the run could fail
  naming codes that were in fact raised. Refuse rather than guess.
- `_is_full_run` is unchanged: the controller has the same `args`, `-k` and `-m` as a single process.
- `unchecked()` stays a per-process flag. A worker runs one test at a time, so this is safe.
- **Alternative: write each worker's codes to a file under the base temp directory.** It works without the xdist hook,
  but invents a protocol xdist already provides (`workeroutput` is the documented channel for this).

### D5: `guard_pytest` is proven under xdist here, and fixed in infrastructure if it isn't

Each worker loads the plugin, collects the whole suite (so `_COLLECTED` is complete in every worker), sets up its own
fixtures (so `_FIXTURES` sees every read the fixtures make in that worker) and rewrites its own tests' teardown
reports, which xdist sends to the controller as they are. By reading the code, it should hold. A pytester test in
`scripts/tests/` checks it: a run with `-n 2 -p guard_pytest`, in a temporary repository whose `scripts/check-paths.toml`
declares a `docs` scope, must fail the untagged test that reads `docs/x.md` with the guard's message, and pass the
tagged one.
If it fails, the fix is made in troupe-run/infrastructure and delivered, and this change waits for it. The copy here
is never edited.

### D6: Shared state is fixed per test, and nothing is marked serial unless serial is the honest answer

The audit in Context found no shared writes, but a search isn't proof. The parallel suite on CI, five runs out of five
on all 12 jobs, is the proof. A test that fails only in parallel gets fixed: its own `tmp_path`, `monkeypatch`, or a
timing bound that holds under load (the rule the flake hunt set). If a test truly can't share the machine, it would
need a second, serial pytest run in `check.py`. That changes D1 and D3, so it comes back here as an update before any
code depends on it. It's not planned.

- **Hypothesis's example database:** in CI the `ci` profile has none. Locally, workers share `.hypothesis/`.
  Hypothesis's directory database keeps each example in its own file under a key directory and is meant for concurrent
  use (a task confirms this in hypothesis's documentation). A failure saved by one worker replays in whichever worker
  next runs that test, which is the behaviour we want. The memory rule stands: a saved failure is fixed, never cleared.

### D7: The evidence is the check step's time per platform, from GitHub's job API

"Before" is the check step of `main`'s most recent successful CI runs, the same measure #83 used. "After" is the five
verification runs of this branch. Both come from `gh api` (the jobs' step timings) and go in the pull request as a
table per platform, with the local time on macOS for both. The five runs are re-runs of the PR's CI workflow. They're
not a local stress loop. Load-heavy local runs need the owner's go-ahead first.

## Risks / Trade-offs

- [Timing-sensitive tests see more load, since 3 to 4 test processes now share the runner] → The flake hunt's
  campaign ran the suite under added load on every platform and came back clean, and its timing rule (fastest of
  several, median with an allowance) is built for load. Any new flake is fixed under D6, and #83 asks for five clean
  runs before relying on it.
- [The single longest test (~21 s) sets the floor, so the gain on a 4-CPU runner is below 4×] → Expected, and
  measured. #84 is where that test gets shorter, with a stated reason.
- [Worker start-up (importing troupe and the guards in each worker) costs a few seconds, which may make the small
  `--scope docs` run slower than one process] → It's accepted for one command shape. The commit's time is dominated by
  mypy and the gates before the tests. Tasks measure the scoped run. If it's clearly slower, the scoped run goes back
  to one process, as a design update.
- [Windows paths get longer under xdist (`popen-gwN/` inside the base temp)] → troupe already handles paths through
  the platform seam. A failure here is a real bug for users with deep paths, and gets fixed rather than worked around.
- [`-ra` and failure output arrive from several workers] → xdist forwards each report to the controller, so the
  summary is the same as in one process. A test of the gate's behaviour on a failing test confirms that the check
  still stops and names the tests gate.
- [The protocol guard's controller hook depends on an xdist hook name] → It's declared with `optionalhook=True`, so
  it's inert without xdist, and the pytester test of D4 fails if xdist renames it.

## Migration Plan

None for users: this is the development toolchain only. To roll back, take `-n auto --dist worksteal` out of
`gates()`. The guard's worker handling is inert without xdist, so it can stay.
