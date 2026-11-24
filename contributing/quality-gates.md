# Merge gates and mutation testing

Besides its linters and tests, `uv run scripts/check.py` runs troupe's merge gates: complexity and file size on every
check, and coverage and the dependency audit on one CI leg. Mutation testing reports on what the tests miss, and never blocks a
merge. This page says where each one runs, what its failure looks like and what to do about it.

The gates' measures are `scripts/quality_gates.py` and `scripts/quality_audit.py`, and mutation testing's are `scripts/mutation_*.py` and
`scripts/mutation.json`. All are delivered from troupe-run/infrastructure: change them there. Its
[development workflow](https://github.com/troupe-run/infrastructure/blob/main/docs/development-workflow.md#the-merge-gates)
says how they work in every repository, and its
[mutation testing](https://github.com/troupe-run/infrastructure/blob/main/docs/development-workflow.md#mutation-testing)
section says how mutation testing works. The thresholds are troupe's own, in `quality-gates.toml` at the root, which isn't
delivered. The gates read it strictly: a misspelt key or a wrong type fails the check rather than switching a gate off.

| Gate | Fails on | Runs |
|---|---|---|
| Complexity | A function the work adds or edits whose cyclomatic complexity is above 25 and is new or higher than before | Every check, local or CI, scoped or full |
| Size | A file the work adds or makes larger that is above 48 KiB, or above its own ceiling; an allowance a file no longer needs | Every check, local or CI, scoped or full |
| Coverage | A package more than 0.6 points below its baseline, a package with no baseline below 80%, or a source file in no package | CI's Linux, Python 3.15 leg, on a full check only |
| Dependency audit | A changed `uv.lock` with a high or critical advisory, or one of unknown severity, that has a fix | CI's Linux, Python 3.15 leg, when `uv.lock` changed |
| Mutation report | Never fails on survivors: it's a report | Each ready pull request, and weekly on `main` |

CI's legs run once a pull request is marked ready, on every merge group, and on `main` after each merge. Each leg passes
`--base`, the commit the work is judged against: a pull request's merge commit's first parent, a merge group's base,
or what `main` was before a push.

## Complexity

The gate measures each function with lizard and compares it with the same function at the base. Locally the base is
where your work left `origin/main` (staged, unstaged and new files included), or the commit you pass with
`uv run scripts/check.py --base <rev>`. Only functions whose lines the work touched are judged. An existing function
above the limit can be edited, as long as the edit doesn't make it more complex.

A failure names each function and stops the check:

```text
complexity: packages/troupe/src/troupe/core/x.py:120 plan: complexity rose from 24 to 27, above the limit of 25
complexity: split the function, or move its branches into named helpers (the limit is [complexity] block_above in quality-gates.toml).
```

A new function says `a new function with complexity 27, above the limit of 25` instead. Split it, or move its branches
into named helpers. To run the gate on its own: `uv run scripts/quality_gates.py complexity`.

- **"the complexity and audit gates compare with origin/main, which this clone doesn't have"**: run
  `git fetch origin main`. Fetch again after a rebase, so the comparison starts from the `main` you rebased on.
- **Left out** (`[complexity] exclude`): tests and the generated config models.

Every gate also leaves out the files infrastructure delivers (the guard, `quality_gates.py`, `quality_audit.py`,
`mutation_*.py` and the rest): `quality_gates.py` reads them from `.github/guard-delivery.json`, so neither
`quality-gates.toml` nor `[tool.coverage.run]` lists them.

## Size

A review reads every changed file whole, and one Read holds about 25,000 tokens, so the gate holds each file a review
reads to about two Reads ([troupe-run/infrastructure#271](https://github.com/troupe-run/infrastructure/issues/271)). It
measures each text file the work adds or changes since the same base as complexity, in bytes, counting a CRLF as one.
Fixtures, archived OpenSpec changes, `uv.lock` and binary files aren't measured (`[size] exclude`).

Each changed file above 32 KiB gets a note, which never fails:

```text
size: note contributing/runners.md is 67,684 bytes, above the warning at 32,768 (more than one Read for a review)
```

A file above 48 KiB fails if it's new or larger than at the base:

```text
size: FAIL openspec/specs/runs/spec.md: grew from 47,411 to 67,892 bytes, above the limit of 49,152
size: split the file so a review can read it in one or two goes, or declare it with a ceiling in [size.allow] (the limits are [size] in quality-gates.toml).
```

Split it: tests by what they test, a spec or a guide by topic. The files that were already over 48 KiB when the gate
came in have their own ceiling in `[size.allow]`, each with an issue to split it. Such a file can grow up to its
ceiling. Once a split brings a file under 48 KiB, the gate fails until its entry is removed:

```text
size: FAIL openspec/specs/runs/spec.md is 47,411 bytes, within the limit of 49,152, so it needs no allowance. Fix: remove its entry from `size.allow`.
```

Adding an entry is a decision for the owner, with a split issue to go with it. To run the gate on its own:
`uv run scripts/quality_gates.py size`.

## Coverage

Coverage is never measured locally, not even on request. CI's coverage leg (Linux, Python 3.15) sets
`QUALITY_GATES_LEG=true`, and `check.py` refuses that variable anywhere but GitHub Actions:

```text
check: QUALITY_GATES_LEG is set, but this isn't GitHub Actions. Coverage and the dependency audit run on CI's coverage leg only (quality-gates design D3). Fix: unset QUALITY_GATES_LEG.
```

On that leg the tests run under coverage.py, branches included. Runners the tests start are measured too: troupe
passes them `COVERAGE_PROCESS_CONFIG`, and each runner ends through `troupe_plugin_sdk.process.exit_now`, which saves
the measurement before it exits ([runners.md](runners.md#cancel-end-of-input-and-shutdown)). A scoped check doesn't
measure coverage, and says `coverage not measured: the tests were scoped`.

Each package in `quality-gates.toml` (`[coverage.packages.<name>]`, with its `paths` and usually a `baseline`) gets a
line in the leg's log:

```text
coverage: troupe: 91.9% (baseline 91.9%, +0.0)
coverage: runner-openai: 91.4% (baseline 91.0%, +0.4); its baseline could be raised to 91.4
coverage: troupe-run: nothing to measure
```

It fails on any of these, each line starting `coverage: FAIL`:

- **`<package> measures X%, Y below its baseline of Z% (tolerance 0.6)`.** Add tests for what your change added.
  The leg keeps its per-file report as the `coverage-report` artifact (`quality-gates-coverage.json`):
  `gh run download <run-id> -n coverage-report`.
- **`<package> measures X%, below the floor of 80.0% for a package with no baseline`.** A package with no baseline is
  held to the floor. Add tests until it meets it.
- **`<file> is in no package. Fix: add it to a package's paths in quality-gates.toml.`** Every source file belongs to
  exactly one package. Add its directory to a package's `paths`, or add a `[coverage.packages.<name>]` entry for a new
  package or runner ([releasing.md](releasing.md#adding-a-package), [runners.md](runners.md#runners-with-client-libraries)).

**Baselines move only by hand.** When the leg says a baseline could be raised, raise it in `quality-gates.toml` in a
pull request, to the number it gives (the measurement, rounded down to 0.1). Record a new package's first baseline
the same way, from the leg's line for it. Lowering one is an ordinary change too: it shows in the diff, so say why in
the pull request. A baseline can be below the floor (`runner-claude-code`'s is): the floor applies only to a package
with none.

## Dependency audit

The audit runs on the coverage leg when `uv.lock` changed since the base, and prints
`audit: no lock file changed, so nothing to audit` otherwise. It audits every package the lock pins with pip-audit,
and takes each advisory's severity from OSV. Each advisory is a line:

```text
audit: FAIL somepkg 1.2.0: GHSA-xxxx-xxxx-xxxx (high, fixed in 1.2.1)
audit: note otherpkg 3.0.0: GHSA-yyyy-yyyy-yyyy (moderate, no fix yet)
audit: update each package above to its fixed version, or pin a fixed version.
```

Only a `FAIL` blocks: a high or critical advisory, or one whose severity can't be found, that has a fixed release.
Update that package to its fixed version, changing only it in the lock (`uv lock --upgrade-package <name>`), or pin
a fixed version. A `note` doesn't block. The audit can't be skipped on a network failure: it fails the leg, so re-run
it. To run it locally: `uv run scripts/quality_gates.py audit`.

Every advisory on `main`, whatever its severity and fix, is in one "Dependency advisories" issue, which
`.github/workflows/dependency-report.yml` opens, updates and closes each Monday, and puts on the board.

## Unit and integration tests

Every suite (each `testpaths` entry in `pyproject.toml`) keeps its tests in two directories, and the directory is a
test's kind:

- **`tests/unit/`**: the test stays inside its own process. It may go through as much of troupe as it likes,
  `main([...])` included, and read and write files in `tmp_path`.
- **`tests/integration/`**: the test reaches outside its process: it starts a process (git included, so every git
  theatre, and troupe or a runner in a child) or opens a socket (a stand-in server, even one on loopback in a thread
  of the test's own process).

Mutation testing runs only the unit tests; the check and CI run both. Run the unit tests alone with
`uv run pytest -m unit` (or `-m "not integration"`, or by naming the `tests/unit/` directories).

`scripts/kinds_pytest.py`, loaded on every pytest run, keeps this true:

- **A unit test that reaches outside fails**, at teardown, naming what it reached (`a process (git) x3`). That
  counts what its fixtures did too (the ones it was actually given, even a session fixture an earlier test set
  up), and what it does through a helper. What a broader-scoped fixture does while being torn
  down isn't counted. Move it to `tests/integration/`, or keep it in-process. An integration test that reaches
  nothing passes: some reach outside on one OS only.
- **A test file in neither directory fails to collect**, naming the file, so the run fails whatever `-m` selects.
- **A kind written by hand** (`@pytest.mark.unit`) fails: the directory is the only source of the kind.
- **No test module imports another.** What tests share goes in a helper module in the suite's `tests/`, beside
  `unit/` and `integration/` (the stand-ins, harnesses, `*testing.py` and `*_shared.py` modules), where both kinds
  import it. A test module that imports another fails, naming both.
- **Each run ends with each kind's count and summed time** (`kinds: unit: 5462 tests, 188.2s summed`).

**What counts as reaching outside** is declared in one place, `OUTSIDE` in `scripts/kinds_pytest.py`: each kind names
the Python [audit events](https://docs.python.org/3/library/audit_events.html) that are that reach. To add one (a
telemetry exporter that leaves the process some other way than a socket, say), add an entry there and an example of
it to `EXAMPLES` in `scripts/tests/integration/test_kinds_pytest_runs.py`; that test fails for a kind without one.
Every unit test that uses the new kind then fails on the next run, naming it.

## Mutation testing

Mutation testing changes the code in small ways (a `+` to a `-`, a `<` to a `<=`) and runs the tests. A change no
test notices is a surviving mutant: a test is missing. It uses mutmut, at the version, budget and threshold in
`scripts/mutation.json`.

**What it covers.** The packages under `packages/` that hold code, each against its own tests (`scripts/mutation.json`'s
`repositories.troupe.units`). The runners under `plugins/` and `scripts/` aren't mutation tested. mutmut can't see
code a test runs in a subprocess, so a function only reached that way counts as reached by no test. A few tests
can't run under mutmut; `scripts/mutation.json` lists them under `deselect`, each with its reason.

### On your pull request

`.github/workflows/mutation-pr.yml` runs when a pull request is marked ready, and on each push after that, never on
a draft. It mutates the functions and lines the pull request changed, on its merge with `main`, within 45 minutes
(`pr_budget_minutes`). It keeps one comment on the pull request, "Mutation testing of this pull request's changes",
edited on each push, listing the mutants that survive on changed lines and the run's time.

- **It isn't a required check**, and it succeeds when it finds survivors. Only its own failure to run fails it.
- **Answer a survivor** with a test that fails for it, or exempt the line with `# pragma: no mutate` and a reason.
- **No comment** when the pull request changed nothing under the packages above and has no comment from an earlier
  push, or when it comes from a fork.

### Weekly

infrastructure's `.github/workflows/mutation.yml` mutates troupe's `main` every Sunday at 03:23 UTC. A module (one
source file) with at least 10 mutants, all run within the budget, is **under** when its score is below 60% or below
its baseline. Each module that's under gets one issue in troupe, labelled `test-quality` and on the board, listing
its surviving mutants. A run opens at most 5 new ones, updates the rest in place, and closes each when its module is
back over. A survivor on a line changed since the last run names the pull request that added it.

troupe was added to the weekly run on 18 November 2026 (infrastructure#332), and the run hasn't completed on troupe
yet, so no `test-quality` issue exists so far. [#455](https://github.com/troupe-run/troupe/issues/455) updates this
page once it has.

**Baselines only move up, by hand.** A module's baseline goes in `quality-gates.toml`, under
`[mutation.baselines."<module>"]`. troupe has none yet. The run never writes one: its summary, and each module's
issue, give the entries to raise, and you raise them in an ordinary pull request.

## Adding a package or a runner

A new package or runner needs its `[coverage.packages.<name>]` entry in `quality-gates.toml` in the same pull request,
or the coverage leg fails on each of its files:

```toml
[coverage.packages.runner-example]
paths = ["plugins/runner-example"]
```

Leave out `baseline` at first: the package is then held to the floor (80%). Add its baseline once the leg has
measured it. A new package under `packages/` is mutation tested only once infrastructure's `scripts/mutation.json`
lists it as a unit, which is a change in troupe-run/infrastructure.
