# Design: theatre-template-and-guard-xdist

## Context

Two unrelated pieces of test tooling, bundled because both came out of the same timing spike and both touch only how
the tests run (troupe-run/troupe#362, #365).

**Theatres.** Tests build their git repositories through a few shared helpers:

| Helper | Where | What it builds | Callers |
|---|---|---|---|
| `make_repo(root, name, branch, refs)` | `packages/troupe/tests/gitrepo.py` | `git init -b <branch>` (reftable when asked), with an empty HOME beside it | 22 files directly, and every user of `theatre()` |
| `theatre(root)` | `packages/troupe/tests/runtesting.py` | `make_repo` plus an empty `.troupe/` | the runs, perform and CLI tests (the per-file `repo` fixtures) |
| `committed(tmp_path)` | `packages/troupe/tests/test_run_workspaces.py` | `theatre` plus `src/a.txt`, `src/b.txt` and `.gitignore`, committed | that file's `repo` fixture |
| `make_repo` fixture | `scripts/tests/conftest.py` | `git init`, three `config` calls, `README.md`, `add`, `commit` | the check's tests |

The spike measured only `committed()`: 131 ms to build, 27 ms to `copytree`. `make_repo` alone is one `git init`, so
its saving is smaller and has to be measured, not assumed.

`test_git_state_cache.py` builds through `make_repo` too (`make_layout_repo`), and tests the stat-and-racy-window
cache on purpose (cache-vcs-state design D4). Its fixture must keep building from scratch.

**The guard.** `guard_pytest` opens a recording window for each collector's collect report, each fixture setup and
each test, and a read joins every open window. A test's reads are its own window, every collector in its
`listchain()`, and its fixtures'. When pytest is given `file::test` arguments, `Session.collect` collects each module
inside the Session's own report (pytest 9.1.1, `_pytest/main.py`, the `matchparts` loop calling `_collect_one_node`).
So the Session's window (node id `""`) holds every selected module's imports, and every test inherits them. Reproduced
on this branch: 2 passed, 2 errors in one process; 3 passed, 2 errors with `-n 2`. Each test was blamed only for the
*other* package's modules (`__pycache__/*.pyc`, sources and the temporary `.pyc.<n>` files written beside them).

`scripts/guard_pytest.py` is delivered from troupe-run/infrastructure. The `delivered-file` rule refuses a change to it
in troupe, and its fix is "change the file in troupe-run/infrastructure, and deliver it from there".

## Goals / Non-Goals

**Goals:**

- Tests that build a common theatre shape get a copy of one built once per test process, and still own their
  repository and HOME.
- A copy looks to git like a fresh build in the ways a test can observe.
- Tests that depend on a fresh `init` keep building their own, by name.
- The saving is measured and recorded, before and after.
- A cross-package selection by node id reports only real out-of-scope reads, in one process and across workers.

**Non-Goals:**

- The git calls troupe makes during a test (#360, #361), and the git adapter's own speed (#367). Nothing under
  `packages/*/src/` changes.
- `test_release_config.py`'s fixture (it copies a workspace, not a theatre) and `test_git_state_cache.py`'s cost.
- Sharing one template across xdist workers. Each worker builds its own (see D2).
- Changing what the guard counts for a test in a full or per-package run. Those runs are clean today, and must stay
  exactly as strict.

## Decisions

### D1. Templates sit behind the existing helpers, whose signatures don't change

`make_repo` and the scripts' `make_repo` fixture copy from a template instead of building. `theatre()` gets the
saving through `make_repo`, since its only addition is a directory. `committed()` gets a template of its own, because
its commit is where most of the 131 ms goes.

A template is keyed by everything that changes what's built: `(branch, refs)` for `make_repo`, nothing more for
`committed()` and the scripts' fixture. The copy goes to `root / name` exactly as now, and HOME is still a new, empty
`root / (name + "-home")`, so a test that writes global config writes its own.

*Alternatives:* a new fixture that tests opt into. Rejected: 22+ files would change, and the issue's count (668 tests)
only falls if the common path is the fast one.

### D2. One template per test process, built on first use, under pytest's base temp

The template for a shape is built the first time a test asks for it, in a directory under
`tmp_path_factory.getbasetemp()`. Under xdist each worker has its own session and base temp, so each builds its own:
no locking, no sharing between processes, and a fresh `--basetemp` gives fresh templates.

`make_repo` is a plain function, also imported by helper scripts that tests start as child processes
(`perform_child.py`, `settle_child.py`, `record_child.py`). So the template directory reaches `gitrepo` through a
session-scoped autouse fixture in `gitrepo.py`, which is loaded as a plugin from `addopts` (`-p gitrepo`), as
`protocol_guard` and `hypothesis_profiles` already are. Where no template directory was set (a child process, or
`gitrepo` used outside pytest), `make_repo` builds from scratch as it does now. That's an absent input, so falling
through is right. The scripts' `make_repo` is already a fixture and takes `tmp_path_factory` directly, which keeps
`scripts/tests` free of a dependency on core's test helpers.

*Alternatives:* `tempfile.mkdtemp()` with `atexit` cleanup. Rejected: it lands outside `--basetemp`, leaks when a
worker is killed, and the measurement needs a fresh base temp to mean anything. Deriving the base temp from `root`'s
parent. Rejected: callers pass other roots.

### D3. A copy looks like a fresh build where git looks

- **File times.** The copy uses `shutil.copy`, not `copy2`, so every copied file has a new modification time, as a
  fresh build's files do. A copy that kept the template's times would put the files outside the racy window that a
  fresh build is inside.
- **The index's stat data.** A copied index records the template's files' times, inodes and ctimes, so git sees every
  entry as stat-dirty. The next `git status` would re-hash them, and could rewrite the index, during what the test
  thinks is a read. For a shape with an index (`committed()`, the scripts' fixture), the copy runs
  `git update-index -q --refresh`, one git process, after which the index matches the copied files as it does after a
  fresh `add` and `commit`. `make_repo`'s shape has no index, and needs no refresh.
- **Object timestamps.** A templated commit carries the time the template was built, which can be minutes before the
  test. The commit's SHA is then the same in every copy within a worker. Two fresh builds within the same second
  already share it, so this is not a new kind of sameness, but a test that reads commit or reflog times against a clock
  it took itself would see the difference. The audit (D4) looks for exactly that.

Each of these is checked by a test (tasks 2.x): a copied `committed()` theatre has `git diff-files --name-only`
empty, as a fresh build does; two copies in one test are independent repositories; and HOME is empty and separate.

### D4. A test that needs a fresh build says so: `make_repo(..., fresh=True)`

`make_repo` gains a keyword-only `fresh: bool = False`. `test_git_state_cache.py`'s `make_layout_repo` passes it,
because it tests object timestamps, the index's stat data and the racy window deliberately.

The rest are found by an audit of every caller of the four helpers, against a written list of what can differ (D3):
the racy window (a test that uses the real clock, not `past_the_racy_window`, and expects a read to be racy or not),
file and index times (`st_mtime`, `st_ctime`, `stat()` of anything under `.git/`), commit and reflog times
(`%ct`, `%cd`, `%at`, `reflog`, `log --date`), and SHAs compared across separately built theatres. Each finding
either passes `fresh=True` with a comment naming which of those it depends on, or is recorded in the PR as checked and
not dependent. Known starting points: `test_store_git.py`, `test_event_service.py` and `record_child.py` use the real
clock and the default racy windows; `test_git_worktrees.py` and `test_config_files.py` read `st_mtime`.

The full suite then runs three times across workers with `--dist worksteal` (`scripts/check.py`'s form, which places
tests differently from run to run), and once in one process, so a dependency the audit missed has several chances to
show.

### D5. The measurement: interleaved, fresh base temp, 3 workers

Baseline is the merge base with `main`, checked out as a detached worktree in the session's scratchpad, created and
removed by this session. Variant is this branch. Each run is
`uv run pytest -n 3 -q --basetemp=<new empty dir> --durations=0`, and the pairs alternate (baseline, variant,
baseline, …), three pairs, because other sessions' load moves a single run's time by 20% or more. Each run records:
wall time, total setup time from `--durations=0`, and the count of fresh builds and copies (a counter `gitrepo` prints
at session end, only when asked for by an environment variable, so a normal run's output doesn't change). Runs start
only when the load average is below 20, and the owner is told before the loop starts.

The numbers go into this design's "Measured" section and the pull request. If a shape's copy is not faster than its
build (`make_repo`'s plain `init` is the one in doubt), that shape builds from scratch, and the design says so.

### D6. The guard counts a collection read against the innermost collector only (infrastructure)

In `guard_pytest`, a read made while collectors are being collected joins only the innermost open collector window,
not the collectors it's nested in. Test and fixture windows are unchanged. So in a run given node ids, each module's
imports belong to that module's collector, and reach only the tests under it. The Session's window keeps only what
the Session itself read outside any nested collector, as in a run given paths, where nothing is nested.

This doesn't make any run less strict. A test's `listchain()` still includes its own module and every collector above
it, and their reads still count. In a full or per-package run no collector's report is made inside another's, so
nothing changes there.

*Alternatives:*

- Drop the Session's window from `_reads`. Rejected: the Session can read files itself (a root `conftest.py`), and
  those are every test's reads.
- Subtract an inner collector's reads from its parents when it closes. Rejected: a parent that read the same file
  itself before the inner one opened would lose it.

The exact code is infrastructure's to decide, in its own issue and change. This design states the behaviour troupe
relies on, and troupe's test (D7) checks it.

### D7. Troupe's test, and the order the two land in

`scripts/tests/test_guard_pytest_workers.py` (troupe's own) gains a pytester case: two scopes, each with a `tests`
directory, one of them with a `conftest.py`, and a test in each that reads only its own package's files. Selected by
node id, run in one process and with `-n 2`, both pass with no `guard:` output. The same selection with a third test
that reads `docs/x.md` untagged fails that test only, naming the file and the tag. Before infrastructure's fix is
delivered, the clean-selection case fails with the false errors #365 describes. That's checked first, so the test is
shown to catch the bug.

Order:

1. The theatre template lands in this branch's commits. It touches no delivered file.
2. An infrastructure issue (on the board, citing troupe#365) and pull request change `guard_pytest.py` and its own
   tests there. The owner merges it and approves the delivery plan, and the App delivers it to troupe's `main`.
3. This branch is rebased on that delivery. The troupe test is added then, since `scripts/check.py` would refuse a
   commit whose test fails on the old guard.
4. One troupe pull request closes #362 and #365.

## Risks / Trade-offs

- **A test silently depends on a fresh build, and the audit misses it** → it fails, sometimes, depending on timing.
  Mitigation: D4's written list, the repeated full runs, and `fresh=True` as a one-word fix when one turns up later.
- **Template contents go stale within a run** (a test writes into the template by mistake) → every later copy is
  wrong. Mitigation: the template lives in a directory no test is given, and copies never link to it (a full copy,
  not hard links, and git's alternates aren't used).
- **The saving is smaller than estimated** for `make_repo`'s plain `init` → D5 measures each shape and drops any that
  doesn't pay.
- **#367 changes the git adapter at the same time** → this change touches no adapter code. If #367 merges first, this
  branch is rebased and the full check rerun; the measurement's baseline is taken from the new merge base.
- **The infrastructure delivery is slower than this branch** → the troupe pull request stays a draft until the
  delivery is on `main`. The theatre work isn't held back by it, and can be reviewed meanwhile.
- **Templates use disk per worker** → a few small repositories per worker, removed with the base temp.

## Migration Plan

None. Test helpers only; nothing ships.

## Measured

To be filled in by task 4 (D5): wall time and total setup time per run, baseline and variant, three interleaved
pairs, and fresh builds against copies.

## Open Questions

None blocking. Whether infrastructure tracks the guard fix as an OpenSpec change or a plain pull request is its own
workflow's call.
