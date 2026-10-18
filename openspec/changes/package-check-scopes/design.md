# Design

## Context

#108 (archived as `pre-commit-hook-configuration`) put the guard's selective check in place: `scripts/check-paths.toml`
declares `[skip]` and `[scopes.<name>]`, the guard runs `check.py --scope <name> ...` when every staged path is skipped
or in a scope, and `guard_pytest` fails a test that reads a scope's path without that scope's marker. A path in no
group runs the full check. `guard.py` and `guard_pytest.py` are delivered from troupe-run/infrastructure and can't be
edited here.

Constraints found while planning (on `c0634ec`):
- **The schema is closed.** A scope holds only `paths`, so it can't say which tests it tags. Tags come from markers,
  and today the only way to put one on a whole suite is `pytestmark` in each of ~90 modules.
- **The plugin's read check can't prove reach.** It sees a module's first import (the `open` audit event), not later
  ones, nor entry-point loads of already-imported modules, nor subprocesses. So reach must be proved statically.
- **Core loads adapters by entry-point group**, one loader module per group: `troupe.core.vcs` (`troupe.vcs`),
  `troupe.core.identity` (`troupe.identity`), `troupe.core.stages` (`troupe.stages`), `troupe.core.artifacts`
  (`troupe.artifacts`) and `troupe.core.events.port` (`troupe.store`). No other workspace code calls
  `entry_points(`.
- **Shared helpers cross suites.** `pythonpath` holds `packages/troupe/tests` and `scripts`, so adapter suites import
  core's helpers (`gitrepo`, `storetesting`, `protocol_schemas`). `protocol_schemas` globs `plugins/*/schemas`, so a
  suite that validates against it reads the scripted runner's schemas.
- **The core suite starts the scripted runner** (`python -m troupe_runner_scripted` in `test_runner_conformance` and
  `test_run_host`) and reads its `fixtures/` (`test_claude_fixtures`).
- **The in-flight `parallel-tests` change** runs the tests gate with `-n auto`. Nothing here changes `check.py`, and
  #86 asks for the `tests` key to be proved under xdist.

### Measured time per suite

One serial run of the whole suite (`pytest --junitxml`, macOS, 1,792 passed and 7 skipped, 266 s wall), test time
summed per tests directory:

| Suite | Tests | Time | Share |
|---|---:|---:|---:|
| core (`packages/troupe/tests`) | 1,410 | 149.7 s | 57.0% |
| store-text | 102 | 62.4 s | 23.8% |
| scripts | 125 | 36.8 s | 14.0% |
| vcs-git | 25 | 8.4 s | 3.2% |
| runner-scripted | 83 | 2.9 s | 1.1% |
| identity-local | 21 | 1.5 s | 0.6% |
| artifacts-local | 21 | 0.8 s | 0.3% |
| vcs-files, stage-local | 6 each | <0.1 s | 0.0% |
| **all** | **1,799** | **262.6 s** | |

### Reach map (projected)

From importing each suite's modules in a fresh interpreter and noting which workspace packages and entry-point
loaders load, plus the file and subprocess reach above. D3's static analysis is authoritative and may widen it, since
it also counts imports inside functions. Every suite but runner-scripted's reaches core.

| Suite | Reaches (besides core) | Why |
|---|---|---|
| core | every adapter, runner-scripted | all five loaders; starts the runner, reads its fixtures and schemas |
| store-text | store-text, vcs-git, vcs-files, identity-local, runner-scripted | imports; vcs, identity and store loaders; `protocol_schemas` |
| stage-local | stage-local, identity-local, store-text, vcs-git, vcs-files | stages, identity, store and vcs loaders |
| identity-local | identity-local, vcs-git, vcs-files | imports; identity and vcs loaders |
| vcs-git, vcs-files | vcs-git, vcs-files | the vcs loader |
| artifacts-local | artifacts-local, runner-scripted | artifacts loader; `protocol_schemas` |
| runner-scripted | runner-scripted | self-contained |
| scripts | scripts | `test_flake_hunt` imports core's platform code only |

### Projected saving, per scope

Test time of the suites each scope runs, against 262.6 s for all. Gates other than tests run either way.

| Scope | Suites it runs | Test time | Saved |
|---|---|---:|---:|
| `scripts` | scripts | 36.8 s | 86% |
| `artifacts_local` | core, artifacts-local | 150.5 s | 43% |
| `stage_local` | core, stage-local | 149.7 s | 43% |
| `store_text` | core, store-text, stage-local | 212.1 s | 19% |
| `identity_local` | core, store-text, stage-local, identity-local | 213.6 s | 19% |
| `runner_scripted` | core, store-text, artifacts-local, runner-scripted | 215.8 s | 18% |
| `vcs_git`, `vcs_files` | core, store-text, stage-local, identity-local, vcs-git, vcs-files | 222.0 s | 15% |

Of the last 284 commits, 114 needed no check and 139 needed the full one. Under these scopes, 26 of the remaining 31
would have run scoped: 8 `scripts`, 7 `docs` with `scripts`, 8 `store_text`, 2 `vcs_git`, 1 `runner_scripted`. The
tasks re-measure on the branch and record the final tables.

## Goals / Non-Goals

**Goals:**
- A scope runs exactly the suites that reach its package, proved on every full run.
- The declaration is the one place that says what a scope covers and what it runs.
- Anything the analysis can't classify runs the full check rather than too little.

**Non-Goals:**
- Splitting the core suite or scoping core's own paths. It reaches everything, and #109 settles that a core change
  runs the full check.
- CI's use of `check-scope` (#101).
- Making `guard_pytest`'s read check see later imports or subprocesses. The static proof replaces that need.

## Decisions

### D1. Scope names and paths

One scope per non-core package, named after the distribution without `troupe-`, with `_` for `-`
(`SCOPE_NAME` allows only `[a-z][a-z0-9_]*`): `artifacts_local`, `identity_local`, `stage_local`, `store_text`,
`vcs_files`, `vcs_git`, `runner_scripted`. Each covers its package's directories as `dir/**` (`src`, `tests`, and for
the scripted runner `fixtures`, `schemas` and `tools`) and its other files by exact path (`README.md`, `LICENSE`),
but not `pyproject.toml`.

`pyproject.toml` stays in no scope, so changing it runs the full check. Found while applying: `release_config.py` and
`python_versions.py` read every workspace member's `pyproject.toml`, and the scripts suite runs them on the real
files. With the whole directory in the scope, the scripts suite would reach every package and every package scope
would run it too (+37 s each, so `stage_local` would save 29% rather than 43%). The static analysis also can't see
those reads, because the paths come from the root's workspace `members` and not from the code. A full check is the
right answer for `pyproject.toml` anyway: it holds the dependencies and entry points, so a change to it can change
what reaches the package. The owner chose this (2026-10-18). A new top-level file in a package runs the full check
until it's declared.

`scripts` lists its files one by one, because the schema has no exclusions and `check.py`, `guard.py`,
`guard_pytest.py` and `check-paths.toml` must run the full check. Exact paths also mean a new script runs the full
check until someone declares it, which is the safe default. `scripts/tests/**` is a directory entry.

`plugins/runner-scripted/README.md` is in `docs` and `runner_scripted`. The guard allows scopes to overlap and runs
both.

*Alternative:* one `adapters` scope. Rejected: the owner chose package granularity, and D3 shows the suites differ
(43% saved for `stage_local` against 15% for `vcs_git`).

### D2. Suites are tagged by the `tests` key, from infrastructure#86

Each scope gets `tests = ["<suite dir>/**", ...]`, and `guard_pytest` adds the scope's marker to every test under
those directories before `-m` deselects. So `check.py --scope vcs_git` runs `pytest -m vcs_git` as now, and selects
whole suites. infrastructure#86 adds the key, its validation, and a refusal when an entry matches no collected test,
so a renamed directory can't quietly stop a suite running.

The owner chose this (2026-10-18) over:
- a troupe-local conftest hook reading a second reach file, which splits one scope across two files;
- `pytestmark` in every module, a hand-kept list of ~90 entries.

`tag_violations` is unchanged, so the read check keeps working: a directory tag counts like a marker.

### D3. Reach is computed statically and compared with the declaration

A troupe-owned module, `scripts/check_paths_reach.py`, computes each suite's reach, and
`scripts/tests/test_check_paths_reach.py` asserts that every package and `scripts` scope's `tests` list equals the
suites whose reach includes it. Equality, not a subset: an extra suite wastes time, and a check that only fails one
way lets the declaration drift wide.

The analysis, using `ast` only:
1. **A suite's code** is every `.py` under its tests directory, plus the helper modules it imports from `pythonpath`
   (`packages/troupe/tests`, `scripts`), followed transitively.
2. **Imports** are every `import` and `from` statement anywhere in that code, including inside functions and
   `TYPE_CHECKING` blocks, mapped to a workspace package by its `src/<module>` directory. Each package reached adds
   its own sources' imports and its `pyproject.toml` workspace `dependencies`, transitively.
3. **Entry points:** a suite whose import closure includes a loader module reaches every package that registers in
   that loader's group, read from each `pyproject.toml`. A loader is any workspace module that calls `entry_points(`;
   its group is read from the call's `group=` argument, a string or a module-level string constant. A call whose
   group can't be read that way fails the analysis, naming the file and line, so a new loader can't go unseen.
4. **Named reach:** a string literal in the suite's code equal to a package's directory name (`runner-scripted`),
   its top-level module (`troupe_runner_scripted`), or `plugins` or `packages` used as a path segment (a glob over
   every plugin or package) reaches that package or all of them. This finds the subprocess and fixture reach without
   a hand list.
5. **Scripts:** a module under `scripts/` that a suite imports, or the `scripts/` directory itself, reaches the
   `scripts` scope, except the four full-check files.

If the analysis misses a case, the fix goes in the module with a comment, not in a hand-kept override list. If a
case can't be expressed (a computed module name), the analysis treats it as reaching every package and says so.

The failure message names the scope, the suites added or missing, and the full `tests = [...]` line to paste.

*Alternatives:*
- **Run each suite in its own process and read `sys.modules`.** Exact for imports, but costs another full run, can't
  see subprocesses or file reads, and depends on what the tests happen to execute. Rejected for the proof; it's what
  produced the projected map above.
- **Generate `check-paths.toml` from the analysis.** Then the declaration isn't the one reviewed place, and the guard
  would read a generated file. Rejected: checking it is enough, and the message gives the text.
- **A coarser entry-point rule** (any suite that reaches core reaches every adapter). Sound and simpler, but it makes
  every adapter scope run the store-text suite, losing 62 s on `stage_local` and `artifacts_local`. The per-loader
  rule is still sound because of the `entry_points(` check in step 3.

### D4. The reach test tags itself with every package scope

`test_check_paths_reach.py` reads every package's sources and `pyproject.toml`, so `guard_pytest` would fail it
untagged, and it should run whenever any package changes, since a change can alter the reach. Its `pytestmark` is
built from the declaration (every scope except `docs`), so adding a scope needs no edit here. So every package
scope runs this one test from the scripts suite as well, which costs well under a second. It also reads
`scripts/` files, which `scripts/tests/**` in the `scripts` scope's `tests` already covers.

### D5. Order of work

infrastructure#86 lands and is delivered first (a `chore(guard): deliver` commit, as for #108). Before that, this
branch can land the reach analysis and its own tests, which don't need the key. The declaration's scopes go in after
delivery, in one commit, which runs the full check (any commit staging the declaration does). Commits after that are
the evidence: one staging only a script runs `--scope scripts`, one staging only a leaf package runs its scope.

## Risks / Trade-offs

- [The analysis under-approximates in a way nobody notices] → Rules 2–4 err wide, unclassifiable code counts as
  reaching everything, a new loader fails the analysis, and `guard_pytest` still catches first reads. Remaining gap:
  a subprocess started by a command built at run time from non-literal parts. None exists today; the test module's
  docstring says so.
- [Static reach is wider than runtime reach] → It may tag a suite that never uses a package, costing time, not
  safety. The tasks compare the static map with the projected one above and record any difference.
- [Order-dependent read violations] → `guard_pytest` attributes a first import to whichever test triggers it. With
  directory tags equal to the reach, every suite is tagged for everything it can import, so no ordering can fail one.
- [xdist changes which test imports first] → Same answer, and #86 proves the key under xdist.
- [Waiting on infrastructure] → Only the declaration waits. The analysis and its tests land first.
- [The `scripts` list goes stale] → A new script falls into no scope, so it runs the full check. The reach test
  doesn't require every script to be listed.

## Migration Plan

1. Land the reach analysis and its tests.
2. After #86 is delivered, add the scopes and their `tests` in one commit; the full check runs.
3. Verify with real commits (D5), and record the re-measured times in the tasks.
4. Rollback: delete the new scopes from `check-paths.toml`. Those paths then run the full check. The reach test
   checks only scopes that exist.
