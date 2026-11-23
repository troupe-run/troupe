# Design

## Context

troupe-run/troupe#507. Mutation testing is to run only the unit tests (owner decision, 2026-11-23). The owner's
decisions on the rule are recorded on the issue (https://github.com/troupe-run/troupe/issues/507#issuecomment-7099737883),
and the survey behind them is at https://github.com/troupe-run/troupe/issues/507#issuecomment-7099087630.

The survey ran every suite on main (06d25b48) on macOS, with a scratch plugin recording each test's time and what it
started, through Python's audit events:

| | tests | summed test time |
|---|---:|---:|
| in-process | 5,438 | 187 s |
| git theatre (and other git) | 980 | 917 s |
| other processes (python children, `fake_claude`, ruff, uv) | 763 | 585 s |
| sockets (the runner plugins' stand-in endpoints) | 397 | 87 s |

The full run took 326 s wall in 6 workers. CI's tests step on main's last merge-queue run (45127049577) took 259 s on
Ubuntu, 651 s on macOS and 781 s on Windows (Python 3.14 legs, and macOS 3.15).

Of 269 test files, 140 are wholly in-process, 53 wholly outside, and 76 hold both. Today every suite's tests sit
directly in its `tests/`, beside its helpers, with no `__init__.py`: pytest imports each test file by its basename
(the default `prepend` import mode), so basenames are unique across the repository, and a suite's helpers are found
because pytest puts the test file's own directory on `sys.path`.

## Goals / Non-Goals

**Goals:**

- Every test has exactly one kind, given by its directory, and the kind is checked against what the test does on
  every run, on every OS CI runs.
- What makes a test integration is decided in one place, which can grow.
- The unit tests can be run alone, by directory or by tag; the numbers #394 needs are measured.

**Non-Goals:**

- Selecting the unit tests for mutation (troupe-run/infrastructure#394).
- Making integration tests faster, or turning integration tests into unit tests.
- Any change to what `scripts/check.py` or CI runs.
- A time limit for unit tests (owner decision 4): time depends on the machine and would flake.

## Decisions

### D1. The directory is the kind

Each suite gets `tests/unit/` and `tests/integration/`, and every test file moves into one of them (owner decision 3).
The suites are the `testpaths` entries: the seven packages, the six runner plugins, `scripts/tests` and
`scripts/tests/workspace`. A file's kind is the first directory under its suite: for `scripts/tests` that's
`scripts/tests/unit/` or `scripts/tests/integration/`, and `scripts/tests/workspace/` is its own suite with its own
two directories, since it's listed apart in `testpaths` and has scopes of its own.

Helpers stay in `tests/`: stand-ins, harnesses, the `*_child.py` scripts, `gitrepo`, `runtesting` and the rest,
and `scripts/tests/conftest.py`. They aren't tests, and the tests of both kinds import them. Fixture data
(`plugins/runner-openai/tests/data/`) stays too.

Alternatives: a marker on each integration test or module (rejected by the owner: a module then holds both kinds, and
the 170 in-process tests in mostly-integration modules go unmutated); a filename convention (`*_integration.py`): it
works with mutmut too, but a directory is what a person and a tool can point at in one argument
(`pytest packages/troupe/tests/unit`).

### D2. pytest finds the helpers through `pythonpath`

Once a test file is in `tests/unit/`, pytest puts `tests/unit/` on `sys.path`, not `tests/`, so its helpers would no
longer import. pytest's `pythonpath` gains every suite's `tests/` (core's already is). Basenames stay unique, so the
`prepend` import mode keeps working; the plugin doesn't need to check uniqueness, since pytest already refuses a
duplicate basename at collection. mypy's `files` and `mypy_path` name directories and need no change, and the
`check-paths.toml` scopes name `tests/**`, which still holds every moved file.

### D3. Splitting a file that holds both kinds

The survey lists, per test function, whether any of its cases reached outside. A file holding both kinds is split by
function: the larger part keeps the file's name and goes to its kind's directory, and the smaller part moves to a new
file named `<stem>_unit.py` or `<stem>_integration.py` in the other one. Keeping the larger part under its own name
keeps the diff small. A test parametrised so that some cases reach outside and some don't (none today) would go to
integration whole.

Module-level helpers that both halves use move to a helper module beside them in `tests/` (the suite's existing
`*testing.py` module when there is one), never imported from the other half: test modules don't import each other.

The survey ran on macOS, so a test skipped there can look in-process when it isn't. Before a minority test moves to
unit, its skip conditions are read; a test that only runs on another OS is classified from its code. CI then confirms
every move on all three OSes, because the detector (D4) fails a unit test that reaches outside on any of them.

### D4. The detector: one registry of outside accesses

New `scripts/kinds_pytest.py`, troupe's own, loaded with `-p kinds_pytest` beside the delivered `guard_pytest`. It
holds the registry, `OUTSIDE`: a tuple of named kinds of access, each listing the Python audit events that are that
kind, and optionally a check that excuses an event that isn't really outside (owner decision 2):

- **a process**: `subprocess.Popen`, `os.posix_spawn`, `os.spawn`, `os.exec`, `os.system`, `os.fork`, `os.forkpty`,
  `os.startfile`. The failure names the program (`git`, `python`, `ruff`).
- **a socket**: `socket.connect` and `socket.bind`, network or Unix-domain, excusing those made inside
  `socket.socketpair` (on Windows it builds the pair with a loopback bind and connect; on Linux and macOS it makes
  no such call), since a pair only links two ends in the same process.

An audit hook records every event in the registry while a test or a fixture runs, as `guard_pytest` records reads:
each test's own setup, call and teardown, and each fixture's setup, charged to every test that uses that fixture,
even after an earlier test set it up. At teardown a unit test with anything recorded fails, naming each kind, how
many times, and for a process its program, and the fix. Integration tests are recorded but never failed for reaching
nothing (owner decision 5: a test can reach outside on one OS only).

**Adding a kind** is one entry in `OUTSIDE` and one example in the detector's tests: the test that every kind is
caught (D5) is parametrised by the registry and fails for a kind with no example, so a kind can't be added untested.
Every unit test that uses the new kind then fails on the next run, with nobody having to look for them. Two likely
later kinds, recorded here so whoever adds them knows where they go:

- *Telemetry export* reaches the network, so its socket is already caught. A kind of its own is needed only for an
  exporter that leaves the process some other way (a file another process reads); it's an entry with the exporter's
  events, or an `open` filter on its path.
- *Files outside the test's temporary directory*: an `open` event whose path is outside `tmp_path` and outside the
  repository. Not added now: the docs tests and the schema tests read the repository on purpose, and the home
  directory is isolated per test by the fixtures that need it. If it's added, it starts from those exclusions.

Alternatives: deciding the kind by fixture names (`theatre`, `stand_in`) would miss a test that calls `subprocess`
directly, and grows a list by hand; a timing threshold flakes (Non-Goals).

Known limit: the hook sees this process only, and attributes an event to the test running when it fires. A thread a
test leaves running that later starts a process charges whichever test is running then. The suite leaves no such
threads today (the survey's unit tests recorded nothing), and the failure names the program, which points at the
thread's owner.

### D5. Tagging, and what the plugin refuses

At collection (`tryfirst`, before `-m` deselects), each test gets the `unit` or `integration` marker from its
directory, so `-m unit` and `-m "not integration"` select the same tests as the `tests/unit/` directories. Both
markers are registered by the plugin. Refused, each as a failing test so every run reports it whatever `-m` selects
(the item carries both markers so a kind selection still includes it):

- a test in neither directory, naming its file and its suite's two directories;
- a hand-written `unit` or `integration` mark: the directory is the one source of the kind.

The plugin's tests are integration tests: they run pytest in a child process (`pytester.runpytest_subprocess`), since
an in-process inner run would charge its events to the outer test. Its pure parts (the kind of a path, an event's
kind) have unit tests.

### D6. Each kind's count and summed time on every run

At the end of every run, the plugin prints one line per kind: how many tests ran and their summed time (setup, call
and teardown). Summed time is what a mutation run pays, since mutmut runs each mutant's tests one after another, and
printing it on every run gives #394 numbers from every CI leg without a separate measuring run. It's a report, not a
gate.

### D7. Moving without breaking: four commits that each pass the check

The owner asked for the moves apart from the edits. Each commit must pass `scripts/check.py`, so the order is:

1. **Splits**, in place: each mixed file becomes its two halves, still in `tests/` (edits).
2. **Location-independent paths**: 57 test files find their suite, plugin or repository from `Path(__file__)` by a
   fixed depth (`parents[3]`, `with_name("record_child.py")`). They find the suite's `tests/` directory by name
   instead, so they work at any depth (edits).
3. **The moves**: `git mv` of every test file, plus the strings that name moved files, which the check reads and so
   can't wait: pytest's `pythonpath`, the flake campaign's selection, `quality-gates.toml`'s per-file size limits,
   `scripts/mutation.json`'s deselected test ids, and the scripts' tests of those. Every moved file is a pure rename.
4. **The detector** and its tests, `-p kinds_pytest`, the contributor docs and the measurements (edits).

### D8. References that follow the moves

- `scripts/flake_campaign.py`'s `SELECTION`: `packages/troupe/tests/*/test_platform_*.py` and the same for the
  run-host and CLI-run files, so a file moving between kinds stays hunted (flake-hunt delta).
- `quality-gates.toml`: the size-limit keys for `test_run_host.py` and `test_platform_processes.py`.
- `scripts/mutation.json`: the three deselected test ids. Each unit's `tests` stays the whole `tests/` directory
  until #394 points it at the unit tests.
- `contributing/`: `flake-hunt.md` and `runners.md` name test files; the testing guidance gains the rule (where a
  new test goes, what the detector checks, how to add a kind).
- Comments in files infrastructure delivers (`claude-review.yml`, `dependabot-dispatch.yml`, `guard.py`) name
  `scripts/tests/test_*.py` files that move. They can't be edited here, so an infrastructure issue updates them
  (on the board).

## Risks / Trade-offs

- **Open pull requests conflict with the moves** → only #505 (config-mv) touches tests today (11 files). git's rename
  detection applies its edits to the moved files on rebase; a split file may need its hunks placed by hand.
- **A test that reaches outside only on Linux or Windows lands in unit** → read skip conditions before moving (D3);
  CI's three OSes run the detector, and the failure names the test and what it started.
- **Code covered only by integration tests looks untested to mutation** → that's the honest signal, and #394 says
  so; it's not this change's to fix.
- **Rename-heavy diff is hard to review** → the moves commit holds only renames and the path strings the check
  reads (D7), and the PR says how to review it (`git log --follow`, `-M`).

## Migration Plan

No user-facing change. Contributors put new tests in `tests/unit/` or `tests/integration/`; a test in neither fails
with the fix. Rollback is a revert of the PR.

## Open Questions

None.
