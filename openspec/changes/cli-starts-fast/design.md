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

### D2. Command declarations stay cheap; each family's body loads when one of its commands runs

`cli.commands`, `cli.config` and `cli.init` keep their `COMMANDS` tables, argument declarations and help text, and
import only argparse, `cli.parser` and cheap core constants. Each command's `run` stays a typed function in the
declaration module, but its body is a one-line deferred import of the family's body module, which holds what is
there today: the rendering of results, the calling helpers and everything they import. Concretely, the shared calling
helpers (`_session`, `_call`, `_notices`, `_ignore_cancel`, with `asyncio`, `dispatch`, `theatre`, `interrupts`)
move to their own body module, which the run, config and init bodies import.

Alternatives: a `run` given as a `"module:function"` string resolved at call time loses mypy's check of the
signature. Deferred imports scattered through today's modules inline, without the split, work but make it easy for a
new top-level import to slip back in. The check (D6) would catch that, but the split makes the boundary something a
reader can see. Constants that `configure` needs (like `core.defaults.RUNTIMES` for `init --runner` choices) stay
top-level imports only if they're cheap. Otherwise they move behind the same deferral, or into a cheap module.

### D3. `--version` reads the version where it's printed

`importlib.metadata.version` is imported inside the `--version` branch of `run`. The installed metadata stays the one
source of the version.

Alternative: a generated `troupe.__version__` constant would be a second copy of the version that release-please
would have to keep in step. Rejected: one decision in one place.

### D4. `cli.render` doesn't import the runner effects module to render an error

`render_error` and `render_notice` are needed by every path. `render`'s use of `core.runners.effects.Change` moves
under `TYPE_CHECKING`, or the change rendering moves to the body that renders a run, whichever keeps the type checks.
`troupe.platform.paths.friendly` stays (cheap).

### D5. The dispatcher imports only the called method's family

`dispatch` gets one table from method name to the module that defines its family's `methods()`. `call` imports that
one module. `handlers()` (all methods) stays for the unknown-method listing and for tests, and the listing comes from
the table's names, so it doesn't import any family. A test checks the table's names equal the union of every family's
`methods()`, so a method added to a family without a table entry fails the suite rather than becoming "unknown".

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

Before (this Mac, 4ddce25, measured while proposing): `import troupe.cli` 411 ms cumulative, 332 modules.
`python -c pass`: 33 modules. The full before/after tables (count by kind, cost by kind, suite estimate, import time
and suite times interleaved) are filled in by tasks 1 and 6.
