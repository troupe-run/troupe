# Proposal

## Why

Mutation testing is to run only troupe's fast unit tests, never the integration tests: that's the owner's standing
practice (owner decision, 2026-11-23, on #507). Today nothing tells the two apart. All 7,578 tests sit in each suite's
`tests/` directory with no classification, so infrastructure's mutation run (troupe-run/infrastructure#378) runs every
test that reaches a mutated function, git theatres and child processes included, and managed only about 500 mutants
per 4-hour run. troupe-run/infrastructure#394, which makes mutation use the unit tests only, is blocked on this.

A survey of main (06d25b48) found the split worth having: 5,438 tests (72%) start no process and open no socket, and
take 187 s summed; the other 2,140 take 1,589 s.

## What Changes

- **Each suite's tests move into `tests/unit/` and `tests/integration/`**: every suite in `testpaths`, the packages,
  the runner plugins and `scripts/tests` (and its `workspace` suite). The directory decides a test's kind, and each
  file is wholly one kind. Helpers (stand-ins, harnesses, child scripts, gitrepo) stay in `tests/`.
- **A test is integration if it reaches outside the test's process**: it starts a process (git included, so every
  git theatre) or opens a network socket (a stand-in server, even on loopback in a thread of the same process),
  itself or through a fixture it uses. Everything else is unit, however much of troupe it goes through: an in-process
  `main([...])` CLI test is unit.
- **Files that hold both kinds are split** (76 files): the smaller part moves to a new file named `<stem>_unit.py` or
  `<stem>_integration.py` in the other directory. That puts 170 in-process tests that sat in mostly-integration files
  into unit, where they're mutated.
- **A new pytest plugin, `kinds_pytest`, checks the claim on every run**: it tags each test `unit` or `integration`
  from its directory before `-m` selects, fails a test that's in neither directory, refuses a hand-written kind
  marker, and fails a unit test that reaches outside its process, naming what it started and the fix.
- **What counts as reaching outside is one named registry** in the plugin (processes and network sockets now). A new
  kind of outside access, such as telemetry export, is added there once, and every unit test that uses it fails
  from then on, without anyone having to remember to look. The detector has its own tests.
- **Nothing is dropped from CI**: `scripts/check.py` and CI still run both kinds. `pytest packages/troupe/tests/unit`,
  `-m unit` and `-m "not integration"` select the unit tests alone. No time limit applies to unit tests, and an
  integration test that started nothing isn't failed.
- References to moved tests follow them: the flake campaign's selection, `quality-gates.toml`'s per-file size limits,
  the contributor docs, and pytest's and mypy's paths. `scripts/mutation.json`'s deselected test ids change in
  infrastructure, which delivers that file.
- The unit set's time on its own is measured before and after, locally and in CI, for troupe-run/infrastructure#394.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `quality-check`: new requirements that every test is unit or integration by its directory, that a test in neither
  fails, that a unit test reaching outside its process fails, that what counts as outside access is declared in one
  place, and that the unit tests can be run alone; the one-process example names a moved test file.
- `flake-hunt`: the campaign's selection names the moved platform, run-host and CLI-run test files by patterns that
  match both kinds' directories.

## Impact

- Every test file moves (`git mv`, kept in commits of their own so the renames review apart from the edits); 76 are
  split first.
- `pyproject.toml`: pytest's `pythonpath` gains each suite's `tests/` (helpers stay there while tests move a level
  down) and `-p kinds_pytest`; mypy's paths are unchanged (they name directories).
- New `scripts/kinds_pytest.py` (troupe's own, beside the delivered `guard_pytest.py`) and its tests.
- `scripts/flake_campaign.py`, `quality-gates.toml`, `contributing/` docs. The delivered `scripts/mutation.json`'s
  three deselected ids move in an infrastructure pull request merged first, naming old and new ids.
- Comments in files infrastructure delivers (`claude-review.yml`, `dependabot-dispatch.yml`, `guard.py`) name
  `scripts/tests/test_*.py` files, but those are infrastructure's own tests, not troupe's, so nothing here moves them.
- Open pull request #505 (config-mv) touches 11 test files and will need a rebase; git's rename detection carries
  its edits to the moved files.
- troupe-run/infrastructure#394 then points mutation at the `unit` directories or `-m unit`.
