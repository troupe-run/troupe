# Tasks

## 1. Count and size, before any code changes (design D1, D7)

- [ ] 1.1 Make the baseline: a detached worktree of this change's base commit outside the repository directory, with
  its own `uv sync`; verify `uv run python -c "import troupe.cli"` runs there and `git -C <it> rev-parse HEAD` is the
  base commit.
- [ ] 1.2 Grep the tests, plugins' tests and scripts for Python launched with `-S` or `-I`, or from an interpreter
  other than `sys.executable`, and list them as processes the count can't see; verify the list is recorded in the
  design's Measurements.
- [ ] 1.3 Add the opt-in counting `.pth` to this worktree's `.venv` only (not committed: `git status` shows nothing
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

- [ ] 2.1 Add a test helper that runs a fresh `sys.executable` doing one thing (import `troupe.cli`, or run
  `troupe.cli.main` with given arguments in a given directory) and returns the names in its `sys.modules`, written to
  a file rather than stdout; verify a helper test that `python -c pass`'s set excludes `jsonschema` and that importing
  `jsonschema` puts it in.
- [ ] 2.2 Name the heavy modules in one place, and add the tests for "Starting troupe loads only what parsing needs":
  importing the command line, `--help`, `troupe` alone, an unknown command, a refused argument, and `--version`
  (which allows only package metadata); each asserts the output and exit code are unchanged too. Verify they fail on
  the base commit, naming the modules (these are the tests group 3 makes pass; mark nothing xfail, and commit them
  with group 3's first passing step so every commit passes the check).
- [ ] 2.3 Add the tests for "A command loads only its own handlers": `troupe status` in a theatre loads neither the
  config nor init handlers, `troupe config get` loads neither the runs nor init handlers; verify they fail on the
  base commit for the reason the scenario names.
- [ ] 2.4 Add a test that the dispatcher's unknown-method listing equals every method the families offer, before and
  after; verify it passes on the base commit (it's the non-goal check: the listing must not change).

## 3. The parsing path loads nothing heavy (design D2, D3, D4)

- [ ] 3.1 Move the shared calling helpers (`_session`, `_call`, `_notices`, `_ignore_cancel` and their imports) out of
  `cli.commands` into their own body module, and update `cli.config`, `cli.init` and any test that patches them;
  verify the CLI tests pass.
- [ ] 3.2 Split `cli.commands` into declarations (`COMMANDS`, `configure` functions, help) and a body module that a
  thin typed `run` per command imports when it runs; verify the run CLI tests (`test_cli_runs.py`, `test_cli.py`,
  `test_cli_changes.py`) pass unchanged apart from patch targets.
- [ ] 3.3 Do the same for `cli.config` (moving `cli.values`' YAML and schema imports off the declaration path) and
  `cli.init` (keeping `--runner`'s choices cheap); verify the config and init CLI tests pass.
- [ ] 3.4 Import `importlib.metadata.version` inside the `--version` branch (D3), and stop `cli.render` importing
  `core.runners.effects` at the top (D4); verify `test_cli_render.py` and the version tests pass.
- [ ] 3.5 Verify group 2.2's tests now pass, run mypy --strict, ruff and import-linter, and commit groups 2.1–2.2 with
  this group (signed, signed off, `uv run scripts/check.py` passing, its full output kept in a scratch file).

## 4. A command loads only its own handlers (design D5)

- [ ] 4.1 Give the dispatcher one table from method name to the module of its family's `methods()`, have `call` import
  only that module, and build the unknown-method listing from the table's names; verify group 2.3's and 2.4's tests
  pass, plus `test_client_dispatch.py`.
- [ ] 4.2 Add the drift test: the table's names equal the union of every family's `methods()`; verify it fails when a
  method is removed from the table in a scratch edit, then restore it. Commit (signed, signed off, full check).

## 5. Heavy core imports on the paths that don't use them (proposal, "Heavy imports in the core")

- [ ] 5.1 With `python -X importtime` on `troupe status`, `troupe logs`, `troupe config get` and `troupe perform` (a
  scripted actor) in a scratch theatre, list which of `importlib.metadata`, `jsonschema`, `referencing` and
  `ruamel.yaml` each loads without using; record the list in the design.
- [ ] 5.2 For each module on that list, move the import to where it's used (`entry_points()` in `core.stages`,
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
