# Proposal

## Why

#108 gave troupe a declaration (`scripts/check-paths.toml`) that skips `openspec/**` and scopes the docs, but every
code change still runs all ~1,800 tests (263 s of test time, measured on `main` at `c0634ec`). Most suites reach only
part of the workspace, so a commit that changes one package can run its own suite and the suites that reach it. The
owner chose package-level granularity (2026-10-15), and #109 asks for it: the clear win is `scripts/` (37 s instead of
263 s). Among the packages, `stage_local` and `artifacts_local` save 43% and `identity_local` 19%; the scripts suite
names the other packages' paths, so their scopes run it and save 1–5% (design: the static result).

## What Changes

- **One scope per package outside core**: `artifacts_local`, `identity_local`, `stage_local`, `store_text`,
  `vcs_files`, `vcs_git` (each `packages/troupe-<name>/`), `runner_scripted` (`plugins/runner-scripted/`), each
  covering its package's files except `pyproject.toml`, and
  `scripts` (every file under `scripts/` except `check.py`, `guard.py`, `guard_pytest.py` and `check-paths.toml`,
  named one by one, plus `scripts/tests/**`). A commit inside one of them runs every gate and only the suites that
  reach it.
- **Paths that stay in no scope run the full check**, as now: `packages/troupe/**` (core and its shared test
  helpers), every package's `pyproject.toml` (it holds the dependencies and entry points), the check and guard files, `protocol/`, the root configuration, and any new package or script until it is
  declared.
- **Each scope names the test directories it runs** with a `tests` key, which `guard_pytest` applies as the scope's
  marker. That key doesn't exist yet: troupe-run/infrastructure#86 adds it, and this change needs its delivery before
  the declaration can use it. The owner chose this over a troupe-local conftest hook or per-module `pytestmark`
  (2026-10-18).
- **The reach map is proved by a test, not kept by hand.** A test in `scripts/tests` works out each suite's reach
  statically: imports anywhere in the suite and its helpers, followed through workspace packages' sources and their
  `dependencies`; entry-point groups, via the core module that loads each group; and paths or commands that name
  another package. It fails a full run when any scope's `tests` differs from the suites that reach it, printing the
  tables to paste. `guard_pytest`'s read check stays as a second net for file reads.
- **Measured saving recorded in the design**, per scope, from a per-suite `--durations` run.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `quality-check`: the declaration gains a scope per non-core package and `scripts`; each scope runs the suites that
  reach it; core, the check and guard files and undeclared paths still run the full check; and a full run fails when
  a scope's suites disagree with the computed reach.

## Impact

- `scripts/check-paths.toml`: eight new scopes with `paths` and `tests`.
- New `scripts/tests/test_check_paths_reach.py` (and a small reach module it uses), tagged with every package scope
  because it reads every package's sources and `pyproject.toml`.
- `scripts/guard.py` and `scripts/guard_pytest.py` change only by delivery from troupe-run/infrastructure (#86).
- `scripts/check.py` is unchanged; `--scope` already takes several names.
- Builds on `parallel-tests` (archived 2026-10-18), which runs the tests gate across pytest-xdist workers, scoped runs
  included. The scopes select the same tests either way, and #86 proves the `tests` key under xdist.
- Out of scope: CI's use of `check-scope` (#101); splitting the core suite further.
