# Design: troupe starts fast

## Context

See proposal.md for why. What the code does today (main at 4ddce25):

- `troupe.cli/__init__.py` imports `importlib.metadata.version` at the top, and every command module:
  `cli.commands` (which imports `asyncio`, `core.client.dispatch`, `core.theatre`, `platform.interrupts`),
  `cli.config` (which imports `cli.values` → `ruamel.yaml`, `referencing`, `core.interim` → `jsonschema`) and
  `cli.init` (which imports `core.runtimes`, `core.defaults`).
- `cli.render` imports `core.runners.effects` (→ `troupe_plugin_sdk.runner`, ~13 ms) for one type.
- A `Command` is `(name, help, configure, run)`. `configure` only declares argparse arguments; `run` does the work.
  The shared calling helpers (`_session`, `_call`, `_notices`, `_ignore_cancel`) live in `cli.commands` and are
  imported by `cli.config` and `cli.init`.
- `core.client.dispatch.handlers()` imports all three method families (`core.runs`, `core.config.commands`,
  `core.init`) on every call, to look one method up or to list them all for `client.unknown-method`.
- `core.stages`, `core.vcs` and `core.artifacts` import `importlib.metadata` at the top for `entry_points()`;
  `core.audition` imports `version` at the top; `core.interim` imports `jsonschema` at the top.

`python -X importtime -c "import troupe.cli"` on this Mac: 411 ms cumulative, 332 modules loaded (33 for
`python -c pass`). The biggest cumulative entries: `cli.config` 204 ms (of which `cli.values` 204 ms), `cli.commands`
110 ms, `core.interim` 92 ms, `jsonschema` 84 ms, `importlib.metadata` 72 ms on its own (the ~124 ms in the issue
counts `email` parsing it pulls in), `referencing` 69 ms, `ruamel.yaml` 40 ms, `asyncio` 26 ms, `cli.render` 25 ms.

Tests spawn troupe in two ways: the installed `troupe` script (`test_cli.py`), and
`[sys.executable, "-c", "... from troupe.cli import main ..."]` (`test_cli_runs.py`). Runner plugins, stand-ins and
child scripts (`perform_child.py`, `record_child.py`, `settle_child.py`, `interrupt_child.py`, the fake runners) are
other Python processes.

Microsoft Defender's real-time scanning on this Mac makes each file operation cost 1.5–2.8 ms, so every timing here is
compared before and after on this machine, never against CI's absolute numbers.

## Goals / Non-Goals

**Goals:**

- Size the suite's gain by a count before changing code, and record before and after numbers measured the same way.
- Make `import troupe.cli`, `--version`, `--help` and usage errors load no heavy module (spec: cli, "Starting troupe
  loads only what parsing needs"), and each command load only its own family's handlers.
- Keep it that way with a check that can't be flaky: it counts modules a fresh interpreter loaded, never time.

**Non-Goals:**

- Making what a command does once it runs any faster (git calls #360/#361, theatre building #362).
- Calling troupe in-process from tests instead of spawning it. If the count shows it's worth it, that's a new issue
  on the roadmap board, raised from this change's results.
- A time budget for startup. Timings are recorded, not asserted.
- Trimming imports of the runner plugins or the plugin SDK, unless the count shows they're a large share of the
  suite's import time. Then the finding is a follow-up issue, not this change.

## Decisions

### D1. Count the suite's processes with a local `.pth` hook, cost each kind with `-X importtime`

A `.pth` file placed in the local `.venv`'s site-packages (never committed) runs a few lines in every Python process
that starts from this environment. When `TROUPE_COUNT_DIR` is set, it registers an `atexit` handler that appends one
JSON line per process: pid, parent pid, `sys.argv`, `sys.orig_argv`, the module count at exit and its lifetime. It
does nothing when the variable is unset, writes nothing to stdout or stderr, and is removed once the counts are taken.
Processes are sorted into kinds by their command line: the troupe CLI (`troupe` script or the `-c "...troupe.cli..."`
form), each runner plugin, each test child script, and other Python (pytest workers, `uv build`, scripts).

The import cost of each kind is measured separately: the median of 10 runs of `python -X importtime` on that kind's
entry module, cumulative time of its top line. The suite's import time is estimated as the sum over kinds of
count × cost, and set against the suite's wall time × 3 workers. Recorded: the count by kind, the cost by kind, the
estimate, and its share of the suite.

Alternatives: `PYTHONPROFILEIMPORTTIME=1` for the whole suite writes the import profile to every process's stderr,
which tests read and assert on, so it would change outcomes. A committed `sitecustomize` or pytest plugin would put
measurement-only code in the repository. The memory of past spikes says this kind of instrumentation goes in an
opt-in `.venv` `.pth` (it needs no branch change and no guard override).

Limits, recorded with the counts: a process started with `-S` or `-I` skips `.pth` files, and a Python from another
environment (uv's own) isn't seen. The apply step greps the tests for `-S`/`-I` launches and lists any as uncounted.
git and other non-Python processes aren't counted (out of scope).

### D2. One cheap command table; each family's work loads when one of its commands runs

A new module, `troupe.cli.table`, holds every command's declaration: its name, help, `configure` (argparse
arguments only) and a typed `run` whose body is a one-line deferred import of the family's module, which it then
calls. `troupe.cli` takes `COMMANDS` from the table. The family modules (`cli.commands`, `cli.config`, `cli.init`)
keep their command bodies, now public (`run_perform`, `run_set`, `init.run` and so on), their rendering and the shared
calling helpers, with every import they had. They no longer define `COMMANDS` or `configure` functions.

Changed while building (the proposal had the declarations stay in the family modules and the bodies move out): the
tests patch the bodies' internals where they are today (`troupe.cli.config._call`, `troupe.cli.commands._call`,
`init_cli.SHELL`), so moving the declarations instead leaves those tests and the bodies' history untouched, and puts
the whole boundary in one module a reader can see. `configure` needed nothing heavy (the `init --runner` choices aren't
declared to argparse).

Alternatives: a `run` given as a `"module:function"` string resolved at call time loses mypy's check of the
signature. Deferred imports scattered through today's modules inline, without the split, work but make it easy for a
new top-level import to slip back in. The check (D6) would catch that, but the table makes the boundary visible.

### D3. `--version` reads the version where it's printed

`importlib.metadata.version`, and `core.schemas.protocol_version` for the protocol version on the same line, are
imported inside the `--version` branch of `run`. The installed metadata stays the one source of the version.
`core.schemas` imported `jsonschema` and `referencing` at the top, though `protocol_version` only reads a JSON file, so
those imports move into `registry()` and `validator()`, the two functions that use them, with the annotations under
`TYPE_CHECKING`. `--version` then loads package metadata and nothing else heavy.

Alternative: a generated `troupe.__version__` constant would be a second copy of the version that release-please
would have to keep in step. Rejected: one decision in one place.

### D4. `cli.render` doesn't import the runner effects module to render an error

`render_error` and `render_notice` are needed by every path. `render`'s use of `core.runners.effects.Change` moves
under `TYPE_CHECKING`, or the change rendering moves to the body that renders a run, whichever keeps the type checks.
`troupe.platform.paths.friendly` stays (cheap).

### D5. The dispatcher imports only the called method's family, and a family only the called handler

`dispatch.FAMILIES` maps each method name to a function that imports its family's `methods()` (typed, rather than a
module name string). `call` imports only that family. The unknown-method listing comes from the table's names, so it
imports no family. `handlers()` (all methods) loads every family, for tests. A test checks the table's names equal the
union of every family's `methods()`, so a method a family adds without a table entry fails the suite rather than
becoming "unknown" (checked by deleting an entry: the test failed).

Found while building: a family isn't enough on its own. `core.runs` imported its three handler modules at the top,
and `runs.perform` imports `sync_files` from config's handlers, so `troupe status` loaded config's handlers through
`perform`. `core.runs`' handler wrappers (which already existed) now import their handler module when called, and
`perform` imports `sync_files` where it syncs, since `runs.queries` and `runs.changes` import `Backends` and
`lease_dir` from `perform`.

Alternative: keep importing all three families. Every command then pays for config's YAML and schema checking and
init's runtimes. Since the table is the one place a method is routed, it is also the place a missing entry is caught.

### D6. The check names heavy modules; it never measures time or a module-count budget

A test helper runs a fresh interpreter (`sys.executable`) that does one thing (imports `troupe.cli`, or runs `main`
with given arguments), then writes the sorted names in `sys.modules` to a file (not stdout, so output assertions are
unaffected). The test fails when any loaded name is, or is under, one of the heavy modules listed in one place: for
the parsing path `importlib.metadata`, `email`, `jsonschema`, `jsonschema_specifications`, `referencing`,
`ruamel.yaml`, `asyncio`, `troupe.core.interim`, `troupe.core.runs`, `troupe.core.config.commands`, `troupe.core.init`
and `troupe.core.runners.effects`. `--version` allows `importlib.metadata` and `email`. Each command's test lists the
other families' handler modules. On failure the message names the module and says how to find its importer
(`python -X importtime`).

A module-count budget was the issue's other option. Rejected as the gate: the count differs between Linux, macOS and
Windows and between Python 3.12 and 3.13 (platform modules, stdlib internals), so a budget is either loose enough to
miss a 50 ms import or tight enough to fail on one leg of the matrix. The counts are still recorded (Measurements) to
show the size of the change.

### D7. Before and after: a baseline worktree, interleaved runs, the same machine

The baseline is a detached worktree of the change's base commit outside this repository directory, with its own
`uv sync`. Each comparison alternates baseline and change runs (B A B A B A) so drift from other load on the machine
falls on both, and the load average is checked to be low (< 20) before each run.

- Import: 20 alternating runs each of `python -X importtime -c "import troupe.cli"`; median and range of the
  cumulative time, and the module count. Also the median wall time of `troupe --version` and `troupe status` in a
  theatre.
- Suite: 3 pairs of `uv run pytest -n 3 --basetemp <fresh empty dir> -p no:cacheprovider -q`, the same arguments in
  both trees; wall time from pytest's summary line, and pass/fail counts, which must match.

Results go in Measurements below and in the pull request body. Absolute numbers are this Mac's, under Defender.

## Risks / Trade-offs

- [A test patches a function where it lives today (e.g. `troupe.cli.commands._call`)] → After the split it patches
  the body module. The suite fails loudly on a stale patch target, and those tests move with the code.
- [A deferred import hides an import error until a command runs] → The suite runs every command. mypy checks deferred
  imports the same as top-level ones.
- [The heavy-module list goes stale when a new heavy dependency arrives] → The list is in one place, and recorded
  counts show growth. A new dependency of the parsing path is visible in review, since the parsing path's modules are
  few.
- [The `.pth` hook is left in the `.venv`] → It does nothing unless `TROUPE_COUNT_DIR` is set, and the task that adds
  it removes it and checks it's gone.
- [Suite runs load the machine other sessions share] → 3 workers, run only when the load is low, one at a time.
- [The gain for the suite is small because spawned troupe processes mostly run `perform`, which needs most of the
  heavy modules anyway] → The count (task 1) says so before code changes. The parsing path and the per-family
  dispatch are still worth doing for people's commands. If the count shows little suite gain, the pull request says so
  rather than claiming one.

## Migration Plan

None. No output, exit code, error, setting or file format changes. Rollback is a revert.

## Measurements

All on the owner's Mac, under Microsoft Defender's real-time scanning: compare rows with each other, never with CI.

Before (4ddce25, measured while proposing): `import troupe.cli` 411 ms cumulative, 332 modules. `python -c pass`:
33 modules.

### The suite's processes (tasks 1.2 to 1.5)

Counted with the opt-in `.pth` hook (D1) in the baseline tree, one full run: `pytest -n 3`, fresh `--basetemp`,
5563 passed and 16 skipped in 735 s (load 15 at the start, 76 at the end, from other sessions). The hook wrote a start
record when each process began and an exit record at exit; 314 processes started, 182 wrote an exit record (runners
and children that are killed, or that leave with `os._exit`, write none).

| Kind | Processes |
|---|---|
| the scripted runner (`-m troupe_runner_scripted`) | 94 |
| pytest: the xdist workers, and the pytest runs tests start (flake hunt, campaign) | 69 |
| scripts the tests run (`flake_hunt.py` 27, `check_range.py` 8, `check_result.py` 5, `flake_campaign.py` 2, `release_check_report.py` 2) | 44 |
| test children (`perform_child.py` 14, store children `-c` 11, `watch_child.py` 5, lock holders 4, `interrupt_child.py` 2, `record_child.py` 1) | 37 |
| Claude Code runner pieces (`fake_claude.py`, the effects server, the runner) | 16 |
| the Ollama and OpenAI runners | 2 |
| **the troupe CLI** (`-c "...from troupe.cli import main..."` running `perform` 4 and `logs` 1; the `troupe` script's `--version` 1) | **6** |
| other short `-c` programs (sleepers, exits, process-tree and file tests, one runner-schema probe) | 46 |
| **all** | **314** |

Not counted: Python started with `-S` or `-I` (the tests have none) and Python from other environments: `uv build` in
`test_package.py`, and the environments `flake_campaign.py`'s tests sync. git and other programs aren't counted
(out of scope).

Each kind's import cost, measured on a quiet machine (load 16–17) in the baseline tree: the median of 10
`python -X importtime` runs of its entry imports, summing the top-level imports' cumulative times:

| Kind | Import (median, range) | Modules | Count | Count × cost |
|---|---|---|---|---|
| pytest worker (`pytest`, `xdist`, `hypothesis`) | 282 ms (264–542) | 391 | 69 | 19.5 s |
| `perform_child.py` | 393 ms (329–547) | 479 | 14 | 5.5 s |
| the scripted runner | 41 ms (39–63) | 123 | 94 | 3.9 s |
| store children (`-c`, `storetesting`) | 308 ms (227–375) | 411 | 11 | 3.4 s |
| **the troupe CLI** (`import troupe.cli`) | **226 ms (205–242)** | **332** | **6** | **1.4 s** |
| Claude Code runner pieces | 36–42 ms | 114–137 | 16 | 0.6 s |
| `python -c pass` | 1 ms | 33 | | |

(Under load, as when proposing, the same `import troupe.cli` read 411 ms.) Not costed: the 44 runs of scripts and
the 46 short `-c` programs. Their exit records show 58 to 152 modules each, against 332 for the CLI, so they add a few
seconds at most. The costed kinds spend about 34 s
importing, against about 1,470 worker-seconds of suite (490 s × 3 workers on a quiet machine): about 2%. The troupe
CLI's share is 1.4 s, under 0.1%. **So this change makes troupe's commands start faster for the people who run them,
and can't move the suite's time measurably.** The largest import cost the suite pays is pytest's own, in its workers
and the pytest runs tests start, then the test children, none of which this change touches (non-goals). Calling troupe
in-process from tests would save at most the CLI's 1.4 s, so it isn't worth an issue.

### Before and after: startup (task 6.1)

20 rounds, each running baseline (4ddce25) then change (e24ab4b), load 14–16 throughout:

| Measure (median, range) | Baseline | Change |
|---|---|---|
| `import troupe.cli`, `-X importtime` | 220 ms (183–284) | 45 ms (28–59) |
| modules loaded by `import troupe.cli` | 332 | 99 |
| `troupe --version`, wall time | 271 ms (171–391) | 93 ms (65–109) |
| `troupe status` in an empty theatre, wall time | 524 ms (355–567) | 360 ms (320–412) |
| `python -c pass`, wall time | 32 ms (19–44) | 33 ms (19–39) |

### Before and after: the suite (task 6.1)

`pytest -n 3 --basetemp <fresh dir> -p no:cacheprovider -q` in each tree, waiting for the 5-minute load average to
fall below 20 before each run. Both trees passed every run: 5563 passed and 16 skipped in the baseline (the same as
the counted run in task 1.4), 5578 passed and 16 skipped in the change (its 15 new startup tests).

| Pair | Order | Baseline | Change |
|---|---|---|---|
| 1 | baseline first | 465 s | 502 s |
| 2 | baseline first | 508 s | 553 s |
| 3 | baseline first | 487 s | 500 s |
| 4 | change first, `--durations=40` | 463 s | 511 s |
| 5 | baseline first, `--durations=0` | 450 s | 625 s |

The change tree was slower in all five pairs, and running it first (pair 4) didn't change that, so this isn't order.
It also isn't traceable to the change:

- The 15 new tests take about 2 s in all (each runs a fresh interpreter for 0.05 to 0.44 s).
- The 40 slowest tests took the same total in pair 4: 298 s in the change, 296 s in the baseline.
- In pair 5, the files that lost most time touch nothing this change edits: `test_release_config.py` (+79 s),
  `test_git_state_cache.py` (+77 s, which works only in temporary repositories), the flake hunt (+26 s) and the bundle
  tests. Run alone and alternated, two rounds each, the change tree was a little faster on both: 125 s against 128 s,
  and 68 s against 75 s. The config tests (all `test_config_*.py`, where the deferred YAML imports run hottest) took
  112 s against 110 s.

So the suite's time on this Mac moves by more than this change could save or cost (the baseline alone ranged 450 to
508 s), and its pattern points at the machine and at how xdist hands out tests, not at the code. Five losses out of five
is still unlikely to be chance alone, so it was left open, and CI's own job timings were agreed as the deciding measure.

Later local runs, on 2026-11-12, didn't repeat the pattern. Three more pairs, alternating which tree went first, came
out at +27, +38 and +23 s, but the load rose to 38–53 during two of them. Then a comparison of three trees
(baseline, a fresh worktree at the change's code with no caches, and this worktree) had one clean pair: change 551 s,
baseline 557 s. Every other run in it was swamped by load (5-minute averages of 28 to 67), and the fresh tree's
second run failed one flake-hunt test on its fixed 120 s limit under that load (filed as #397, untouched by this
change).

**CI decides it: no slowdown.** The test gate's time (`tests passed in`, from each check job's log) on the pull
request's run against three recent merge-queue runs of main (each main plus one other pull request):

| OS | main: 12 legs, 3 runs | this change: 4 legs (run 43200846522, dacd993d) |
|---|---|---|
| Linux | median 185 s (156 to 214) | median 191 s (187 to 199) |
| macOS | median 481 s (237 to 520) | median 411 s (343 to 459) |
| Windows | median 715 s (480 to 781) | median 703 s (556 to 796) |

Every leg of the change falls inside main's range, as the process count predicts: the suite starts too few troupe
CLI processes for this change to move its time either way.

### What each command loads (task 5.1)

Measured with `python -X importtime` and `sys.modules` in a scratch theatre, after groups 3 and 4:

| Command | Modules | Heavy modules loaded | Used there? |
|---|---|---|---|
| `status` | 381 | metadata, `jsonschema`, `referencing`, `ruamel.yaml`, `asyncio` | metadata yes (event store entry points); the rest no: `runs.queries` imported `runs.perform` for `Backends` and `lease_dir` |
| `config get`, `flush` | 370 | the same | metadata yes; YAML and schemas no: `cli.values` (only `config set` types values), `core.interim`, `config.projection` and `config.kinds` imported them at the top for annotations or for rendering |
| `perform`, `init` | 384, 358 | the same | yes, on the paths that check options or render files |

Changed (task 5.2): `Backends` and `lease_dir` move to `core.runs.backends`, which `perform` re-exports; `cli.config`
imports `cli.values` in `run_set`; `core.interim` and `core.config.kinds` import `jsonschema` only for type checking;
`core.config.projection` imports `ruamel.yaml` where it renders. After: `status` 287 modules, `config get` and `flush`
293, `logs` (a run that isn't there) 203, each loading only package metadata and `asyncio` of the heavy ones.
`importlib.metadata` stays wherever an entry point is read (`core.events.port`, `core.identity`, `core.vcs`,
`core.stages`, `core.artifacts`), since every command that opens a theatre reads one.

