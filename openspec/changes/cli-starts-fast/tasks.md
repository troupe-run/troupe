# Tasks

## 1. Count and size, before any code changes (design D1, D7)

- [x] 1.1 Make the baseline: a detached worktree of this change's base commit outside the repository directory, with
  its own `uv sync`; verify `uv run python -c "import troupe.cli"` runs there and `git -C <it> rev-parse HEAD` is the
  base commit.
- [x] 1.2 Grep the tests, plugins' tests and scripts for Python launched with `-S` or `-I`, or from an interpreter
  other than `sys.executable`, and list them as processes the count can't see; verify the list is recorded in the
  design's Measurements.
- [x] 1.3 Add the opt-in counting `.pth` to this worktree's `.venv` only (not committed: `git status` shows nothing
  new); verify a `python -c pass` with `TROUPE_COUNT_DIR` set writes one line, and without it writes nothing and
  prints nothing.
- [ ] 1.4 With the load average under 20, run the full suite once with `TROUPE_COUNT_DIR` set
  (`uv run pytest -n 3 --basetemp <fresh dir> -p no:cacheprovider -q`, output kept in a scratch file); verify its
  pass/fail counts match an uninstrumented run, then sort the records into kinds (troupe CLI, each runner plugin,
  each test child script, other Python) and record the count by kind.
- [ ] 1.5 Measure each kind's import cost (median of 10 `python -X importtime` runs of its entry module) and record
  the estimate (count × cost, summed) against the suite's wall time × 3 workers in the design's Measurements; verify
  the table adds up from the raw records kept in the scratchpad.
- [ ] 1.6 Remove the counting `.pth`; verify it's gone and `git status` is clean. If the count shows calling troupe
  in-process from tests would win more than this change, raise that as a new issue on the roadmap board
  (`--project "troupe roadmap"`, citing #383) and link it from the design; otherwise say in the design why not.
- [ ] 1.7 Record the before import numbers interleaved with the baseline (D7: 20 alternating runs of
  `-X importtime -c "import troupe.cli"`, module count, median wall time of `troupe --version` and `troupe status`);
  commit the design's Measurements update (signed, signed off); verify `openspec validate cli-starts-fast --strict`.

## 2. The check, written first (spec: cli, both requirements; design D6)

- [x] 2.1 Add a test helper that runs a fresh `sys.executable` doing one thing (import `troupe.cli`, or run
  `troupe.cli.main` with given arguments in a given directory) and returns the names in its `sys.modules`, written to
  a file rather than stdout; verify a helper test that the probe reports `troupe.cli` when it imported it, and that a
  name counts as loaded when a submodule is, but not when only a longer name is.
- [x] 2.2 Name the heavy modules in one place, and add the tests for "Starting troupe loads only what parsing needs":
  importing the command line, `--help`, `troupe` alone, an unknown command, a refused argument, and `--version`
  (which allows only package metadata); each asserts the output and exit code are unchanged too. Verify they fail on
  the base commit, naming the modules (these are the tests group 3 makes pass; mark nothing xfail, and commit them
  with group 3's first passing step so every commit passes the check).
- [x] 2.3 Add the tests for "A command loads only its own handlers": `troupe status` in a theatre loads neither the
  config nor init handlers, `troupe config get` loads neither the runs nor init handlers; verify they fail on the
  base commit for the reason the scenario names.
- [x] 2.4 Add a test that the dispatcher's unknown-method listing equals every method the families offer, before and
  after; verify it passes on the base commit (it's the non-goal check: the listing must not change).

## 3. The parsing path loads nothing heavy (design D2, D3, D4)

- [x] 3.1 Add `troupe.cli.table` with every command's name, help, `configure` and a typed `run` that imports its family's
  module when it runs (design D2), and take `troupe.cli.COMMANDS` from it; verify `test_cli.py`'s help and parser
  tests pass.
- [x] 3.2 Remove the declarations from `cli.commands`, `cli.config` and `cli.init`, making their command bodies public,
  and leave their helpers and imports where they are; verify the CLI tests (`test_cli*.py`, `test_user_docs_*.py`,
  `test_credential_leak.py`, `test_config_paths.py`) pass with no test changed.
- [x] 3.3 Run the startup tests and follow each module still loaded to its importer with `python -X importtime`;
  verify every parsing-path test of group 2.2 names nothing it shouldn't.
- [x] 3.4 Import `importlib.metadata.version` and `protocol_version` inside the `--version` branch, move
  `core.schemas`' `jsonschema` and `referencing` imports into the functions that use them (D3), and stop `cli.render`
  importing `core.runners.effects` at the top (D4); verify `test_cli_render.py`, `test_schemas.py` and the version
  tests pass.
- [x] 3.5 Verify group 2.2's tests now pass, and run mypy --strict, ruff and import-linter. (Committed with group 4,
  in one commit: group 4's edits are in tracked files, and the guard refuses a commit while any is unstaged.)

## 4. A command loads only its own handlers (design D5)

- [x] 4.1 Give the dispatcher one table from method name to its family's `methods()`, have `call` import only that
  family, and build the unknown-method listing from the table's names; have `core.runs`' wrappers import their handler
  module when called, and `perform` import `sync_files` where it syncs (design D5); verify group 2.3's and 2.4's tests
  pass, plus `test_client_dispatch.py`.
- [x] 4.2 Add the drift test: the table's names equal the union of every family's `methods()`; verify it fails when a
  method is removed from the table in a scratch edit, then restore it. Commit groups 2 to 4 (signed, signed off, the
  full check passing, its output kept in a scratch file).

## 5. Heavy core imports on the paths that don't use them (proposal, "Heavy imports in the core")

- [x] 5.1 With `python -X importtime` on `troupe status`, `troupe logs`, `troupe config get` and `troupe perform` (a
  scripted actor) in a scratch theatre, list which of `importlib.metadata`, `jsonschema`, `referencing` and
  `ruamel.yaml` each loads without using; record the list in the design.
- [x] 5.2 For each module on that list, move the import to where it's used (`entry_points()` in `core.stages`,
  `core.vcs`, `core.artifacts`; `version` in `core.audition`; `jsonschema` in `core.interim`), keeping type-only uses
  under `TYPE_CHECKING`; extend group 2.3's tests to assert the module isn't loaded on that command's path; verify
  mypy --strict and the suite pass. Commit (signed, signed off, full check).

## 6. After numbers and integration

- [ ] 6.1 With the load under 20, record the after numbers interleaved with the baseline (D7): 20 alternating import
  runs, module counts, `troupe --version` and `troupe status` wall times, and 3 pairs of suite runs (B A B A B A,
  each with a fresh `--basetemp`); verify both trees' pass/fail counts match, and fill in the design's Measurements
  with the medians and ranges, noting they're this Mac's numbers under Defender.
- [ ] 6.2 Remove the baseline worktree once its numbers are recorded (it's not in use by a session: check `lsof +D`
  first); verify `git worktree list` no longer shows it.
- [ ] 6.3 `openspec validate cli-starts-fast --strict` passes; open a draft pull request whose body closes #383 and
  carries the before/after tables; verify CI passes on Linux, macOS and Windows once it's marked ready.

## Workflow follow-up

- Act on Claude's review of the last push, archive the change on the branch, and ask the owner to merge.
- After the merge, comment on #383 with the PR and the archived change, check it's closed and its card on the
  roadmap board says Done.
