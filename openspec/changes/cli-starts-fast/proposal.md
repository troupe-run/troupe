# Proposal: troupe starts fast

## Why

`import troupe.cli` takes 0.4–0.5 s on macOS before troupe does anything (troupe-run/troupe#383): 411 ms and 332
modules at 4ddce25, against 33 modules for `python -c pass`. Every command a person runs pays it, and so does every
troupe process a test spawns. That is one of the costs behind #382, where the macOS CI legs run close to their
20-minute limit. Most of it is modules the command being run never uses: `importlib.metadata` (~124 ms with its
`email` parsing, read only for `--version` and entry points), `jsonschema` and `referencing` through
`troupe.core.interim` (~83 ms, needed only where a value is checked against a schema), `asyncio` (~54 ms),
`ruamel.yaml` (~35 ms) and `troupe.cli.render` (~30 ms, which pulls in the runner effects module).

## What Changes

- **Count first, before any code changes.** Count how many troupe processes, and other Python processes, a full test
  suite run spawns, sorted by kind (the `troupe` CLI, runner plugins, the tests' child scripts), and estimate the time
  they spend importing. That sizes what this change can win for the suite, and says whether calling troupe in-process
  from tests is worth a separate issue.
- **`import troupe.cli` loads only what parsing needs.** The command table (names, help, arguments) stays cheap to
  import. Each command's body, and the modules it needs, load when that command runs. `--version`, `--help` and a
  usage error don't load `importlib.metadata` (apart from `--version`), `jsonschema`, `referencing`, `asyncio`,
  `ruamel.yaml` or the core's command handlers.
- **A command loads only its own handlers.** The dispatcher imports the handlers of the method it's called with, not
  every method's handlers, so `troupe status` doesn't load config's or init's code. The list of known methods for
  `client.unknown-method` is unchanged.
- **Heavy imports in the core move to where they're used**, where the count shows they're paid on paths that don't
  need them: `importlib.metadata` only where entry points or versions are read, `jsonschema` only where a schema is
  checked.
- **A check keeps it fast without being flaky.** Tests run a fresh interpreter and fail when `import troupe.cli`, or
  `troupe --version`, `--help` or a usage error, loads a named heavy module, and when a command loads another command
  family's handlers. They count modules, not time.
- **Before and after numbers are recorded** in the design and the pull request: the import time of `troupe.cli`, and
  the suite with 3 xdist workers and a fresh `--basetemp`, run interleaved with a baseline on the same machine.

No command's output, exit code or errors change.

Out of scope: calling troupe in-process from tests instead of spawning it (a separate issue, if the count justifies
it); git calls (#360, #361, PR #367); theatre building (#362).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `cli`: a new requirement, that starting troupe loads only what the command it runs needs, checked by the modules it
  loads.

## Impact

- `packages/troupe/src/troupe/cli/`: command declarations split from their bodies, with each body imported when its
  command runs; `--version` reads the version lazily.
- `packages/troupe/src/troupe/core/client/dispatch.py`: a method's handlers are imported when it's called.
- Core modules that import `importlib.metadata`, `jsonschema` or `ruamel.yaml` at the top only for one path
  (`core/stages.py`, `core/vcs.py`, `core/artifacts.py`, `core/audition.py`, `core/interim.py`, `cli/values.py`),
  where the count shows it matters.
- New tests in `packages/troupe/tests/` that run a fresh interpreter. No new dependencies, settings or error codes.
- The measurement tooling (a counting hook in the local `.venv`, timing scripts) stays out of the repository; its
  method and results are recorded in the design.
