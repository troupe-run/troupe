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

Every comment since the previous statement travels with the next one, so a section's comment stays with the tests
below it. Each half keeps the original docstring (the split-off half only its first paragraph) and says where the
other half is. Where a unit half's first paragraph described the integration tests ("driving real runner
processes"), `test-docstrings.json` gives it one that says what its tests check (#510's review found these).

Module-level helpers that both halves use move to a new helper module, `<topic>_shared.py` (the stem without
`test_`), beside them in `tests/`. A shared fixture is defined there as `<name>_fixture` with `name="<name>"`, and
imported under that name with `# noqa: F401`: pytest registers it by its own name, and a test's parameter of the
fixture's name then doesn't redefine the import (ruff's F811).

### D3a. No test module imports another, and helpers live beside both kinds

Before this change, 20 test modules imported names from other test modules (`from test_perform import
configured`). Once tests sit in `unit/` and `integration/`, pytest finds such a module only from the importer's own
directory, so an import across kinds fails, and mypy, whose path names each suite's `tests/`, finds none of them. So
**no test module imports another test module**, of either kind: every name one imports from another moves, with the
helpers it reaches, into the source's `<topic>_shared.py`, and both import it from there (two names that already had
a natural home move to `runtesting.py` and `ollama_harness.py`).

**Every helper lives in its suite's `tests/`, beside `unit/` and `integration/`**, never inside either: the stand-ins,
harnesses, child scripts, `*testing.py` and `_shared.py` modules alike. Both kinds import them, and neither kind's
directory depends on the other's. A helper isn't a test and has no kind: a unit test may import a helper that can
start a process, and stays unit as long as it doesn't call that part. If it does, the detector (D4) fails it at run
time, naming the process, however many helpers lie between.

The plugin refuses the rule's breach at collection (D5): a test module that imports another test module fails,
naming both. The split script does all of this mechanically (`untangle`), so a rebase re-runs it.

The survey ran on macOS, so a test skipped there can look in-process when it isn't. Before a minority test moves to
unit, its skip conditions are read; a test that only runs on another OS is classified from its code. CI then confirms
every move on all three OSes, because the detector (D4) fails a unit test that reaches outside on any of them.

### D4. The detector: one registry of outside accesses

New `scripts/kinds_pytest.py`, troupe's own, loaded with `-p kinds_pytest` beside the delivered `guard_pytest`. It
holds the registry, `OUTSIDE`: a tuple of named kinds of access, each listing the Python audit events that are that
kind, and optionally a check that excuses an event that isn't really outside (owner decision 2):

- **a process**: `subprocess.Popen`, `os.posix_spawn`, `os.spawn`, `os.exec`, `os.system`, `os.fork`, `os.forkpty`,
  `os.startfile`. The failure names the program (`git`, `python`, `ruff`). A process the standard library's
  `platform` module starts (`uname`, `file`, to describe this machine) isn't counted: libraries cache its answer
  (the OpenAI SDK's headers do), so it would fall on whichever test asked first in a process. The serial run of the
  unit set found exactly that.
- **a socket**: `socket.connect` and `socket.bind`, network or Unix-domain, excusing those made inside
  `socket.socketpair` (where the platform has no native pair, Windows, `socket.py` binds that name to
  `_fallback_socketpair`, which builds the pair with a loopback bind and connect; on Linux and macOS it makes
  no such call), since a pair only links two ends in the same process.
- **a git theatre**: `troupe.tests.theatre`, an audit event core's `gitrepo` helper raises for every repository it
  hands a test, copied or built. A theatre is copied from a template each test process builds once, so only the test
  that happens to build it runs git: by processes alone, 27 theatre tests looked in-process or not depending on test
  order (found by the detector's first full run). The event makes every test with a theatre integration, in any order.
  It's also the pattern for a reach the hook can't see directly: the helper that does it raises its own event.

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

Which fixtures count: the definitions the test was actually given (pytest's own per-test record, which resolves an
override and includes a fixture reached through `request.getfixturevalue`), not every definition of a name. Only a
broader-scoped fixture's setup is recorded apart, and its record is replaced when it's set up again (for another
parameter), as its cached value is; a function-scoped fixture runs inside its test's own window. What a broader-scoped
fixture does while being torn down is no test's: that runs inside whichever test comes last, so recording pauses
from its first finalizer to its last. (These came from a review of the plugin before the pull request's review.)

Known limits: the hook sees this process only, and attributes an event to the test running when it fires. A thread a
test leaves running that later starts a process charges whichever test is running then; the suite leaves no such
threads today, and the failure names the program, which points at the thread's owner. `multiprocessing`'s spawn and
forkserver start methods start their process through `_posixsubprocess.fork_exec`, which raises no audit event on
Linux and macOS (Windows' `_winapi.CreateProcess` is declared); nothing in the repository uses `multiprocessing`, and
a test that does would need a kind for it first.

### D5. Tagging, and what the plugin refuses

At collection (`tryfirst`, before `-m` deselects), each test gets the `unit` or `integration` marker from its
directory, so `-m unit` and `-m "not integration"` select the same tests as the `tests/unit/` directories. Both
markers are registered by the plugin.

A test file in neither directory fails to collect (a collection error naming it and its suite's two directories): a
test with no kind can't be selected by a kind, so failing the file's collection is the way every selection reports
it. In one process that stops the run; across workers the other tests still run, and the run fails. (A usage error
raised on xdist's workers became an internal error with the message lost, so it isn't one.) The others are refused as a failure of the test at teardown, as `guard_pytest` refuses
(pytest counts it as an error after the test's call):

- a hand-written `unit` or `integration` mark: the directory is the one source of the kind;
- a test module that imports another test module (`from test_x import`, `import test_x`, at any depth in the
  module), naming both: shared names belong in a helper module in `tests/` (D3a). It's read from the module's source
  with `ast`, so it holds whichever kind of test does the importing.

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

1. **Splits**, in place: each mixed file becomes its two halves, still in `tests/`, and every name one test module
   imports from another moves to a helper (D3a) (edits).
2. **Location-independent paths**: 57 test files find their suite, plugin or repository from `Path(__file__)` by a
   fixed depth (`parents[3]`, `with_name("record_child.py")`). They find the suite's `tests/` directory by name
   instead, so they work at any depth (edits).
3. **The moves**: `git mv` of every test file, plus the strings that name moved files, which the check reads and so
   can't wait: pytest's `pythonpath`, the flake campaign's selection, `quality-gates.toml`'s per-file size limits,
   and the docs that name test files. Every moved file is a pure rename.
4. **The detector** and its tests, `-p kinds_pytest`, the contributor docs and the measurements (edits).

### D8. References that follow the moves

- `scripts/flake_campaign.py`'s `SELECTION`: `packages/troupe/tests/*/test_platform_*.py` and the same for the
  run-host and CLI-run files, so a file moving between kinds stays hunted (flake-hunt delta).
- `quality-gates.toml`: the size-limit keys for `test_run_host.py` and `test_platform_processes.py`.
- `scripts/mutation.json` is delivered by infrastructure (`.github/guard-delivery.json`), so it isn't edited here.
  Its three deselected tests all land in `integration/`, two of them in split-off files
  (`integration/test_cli_startup.py`, `integration/test_config_schemas_integration.py`,
  `integration/test_package_integration.py`); infrastructure delivers a `mutation.json` naming both the old and the
  new ids before this merges, so troupe's pull request mutation run never breaks. Once mutation runs only the unit
  tests (#394), none of the three runs at all. The move script skips every delivered file.
- `contributing/`: `flake-hunt.md` and `runners.md` name test files; the testing guidance gains the rule (where a
  new test goes, what the detector checks, how to add a kind).
- Comments in files infrastructure delivers (`claude-review.yml`, `dependabot-dispatch.yml`, `guard.py`) name
  `scripts/tests/test_claude_review_workflow.py` and `test_dependabot_dispatch_workflow.py`. Those are
  infrastructure's own tests (troupe has no such files), so the moves leave the comments right and need no
  infrastructure change.

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
