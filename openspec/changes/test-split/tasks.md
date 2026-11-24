# Tasks

## 1. The classification, from the survey

- [x] 1.1 Write the per-function plan from the survey: for each of the 269 test files, its kind, or for the 76 mixed
  files, which functions move to `<stem>_unit.py` or `<stem>_integration.py` (D3). Verify: every collected test
  function appears in the plan exactly once.
- [x] 1.2 For each test the plan moves to unit, read its skip conditions; a test that only runs on Linux or Windows is
  classified from its code, and the plan notes it. Verify: the plan lists each such test with its reason.

## 2. Splits, in place (commit: edits only)

- [x] 2.1 Split each mixed file into its two halves in its current `tests/` directory, moving shared module-level
  helpers into a helper module in `tests/`, and move every name one test module imports from another into a helper
  (D3a). Verify: no test module imports another (ast scan); the collected test ids
  before and after are the same set apart from the file part, compared by script; `uv run scripts/check.py` passes.

## 3. Location-independent paths (commit: edits only)

- [x] 3.1 Make every test file that finds its suite, plugin or repository from `Path(__file__)` by a fixed depth find
  the suite's `tests/` directory by name instead (D7.2). Verify: no test file uses `parents[` or `with_name(` on its
  own `__file__` (grep), and the check passes.

## 4. The moves (commit: renames, and the paths the check reads)

- [x] 4.1 `git mv` every test file into its suite's `tests/unit/` or `tests/integration/` per the plan, and add every
  suite's `tests/` to pytest's `pythonpath`. Verify: `git show --stat -M` shows every moved test file as a 100%
  rename.
- [x] 4.2 Update the strings the check reads that name moved files: `scripts/flake_campaign.py`'s `SELECTION` (patterns
  matching both kinds), `quality-gates.toml`'s size-limit keys, the docs naming test files (`scripts/mutation.json` is delivered: its new ids go to infrastructure), and
  any scripts' test that names one. Verify: the flake campaign's pattern test passes, the size gate passes, and
  `uv run scripts/check.py` passes on this commit.

## 5. The detector

- [x] 5.1 Add `scripts/kinds_pytest.py`: the `OUTSIDE` registry (a process; a socket, excusing `socket.socketpair`),
  the audit hook recording per test and per fixture, tagging from the directory before `-m`, and the refusals (neither
  directory, hand-written kind, a test module importing another) as failing tests (D3a, D4, D5). Verify: tests in
  5.2 and 5.3.
- [x] 5.2 Unit tests of its pure parts: a path's kind for each suite shape (`packages/x/tests/unit`,
  `scripts/tests/workspace/integration`, a file in neither), and an audit event's kind for each registry entry.
  Verify: they pass under `tests/unit/`.
- [x] 5.3 Integration tests running pytest in a child process: for every kind in `OUTSIDE` (parametrised by the
  registry, failing for a kind with no example) a unit test using it fails naming the kind and the same test under
  `tests/integration/` passes; a process started by a session fixture an earlier test set up fails the later unit
  test; a socket pair passes; a file in neither directory fails naming both directories, and is selected by `-m unit`;
  a hand-written mark fails; a test module importing another test module (unit from integration, and same kind)
  fails naming both; a unit test starting git through a helper fails; `-m unit` and `-m "not integration"` select the same tests; the run ends with each
  kind's count and summed time; the same results under `-n 2`. Verify: they pass, and each fails when its check is
  removed from the plugin (tried once by hand).
- [x] 5.4 Add `-p kinds_pytest` to pytest's `addopts`. Verify: the full check passes with every test tagged, and
  `uv run pytest -m unit --collect-only -q` collects only files under `tests/unit/`.

## 6. Docs and references

- [x] 6.1 Contributor docs: where a new test goes, the rule, what the detector checks, how to add a kind (D4), and
  the moved paths in `contributing/flake-hunt.md` and `contributing/runners.md`. Verify: the docs tests pass, and grep
  finds no stale `tests/test_*.py` path outside delivered files and archived changes.
- [x] 6.2 Check whether the comments in delivered files name moved troupe test files, and open an infrastructure
  issue (on the board) only if they do. Verify: every `scripts/tests/test_*.py` they name is absent from troupe's
  tree (`git ls-files`), so they name infrastructure's own tests and no issue is needed.

## 7. Measurements for troupe-run/infrastructure#394

- [x] 7.1 After the moves, locally: wall time of `pytest -m unit -n auto`, of `pytest -m unit` in one process, and of
  the full run, against the survey's 326 s; with the owner's slot. Verify: the numbers are posted on #507.
- [ ] 7.2 In CI: each leg's per-kind summary line from the PR's ready run, against main's tests step (259 s Ubuntu,
  651 s macOS, 781 s Windows). Verify: the table is posted on #507 and linked from infrastructure#394.

## Workflow follow-up

- Draft PR closing #507; act on the review; mark ready; archive on the branch; the owner merges.
- After the merge: check #507 closed and its card is Done; tell infrastructure#394 the unit directories and `-m unit`
  are in place.
