# Proposal

Issue: troupe-run/troupe#34 (part A of the walking skeleton, #33). Decisions: #16 (scripted runner first), #4
(transcripts by content hash, local store).

## Why

Every later slice of troupe runs an actor, and actors are third-party code that only ever runs out of process. The
walking skeleton (#33) needs that seam first: a language-neutral contract that any runner can implement, and a
runner that lets tests drive every outcome deterministically, offline and for free. Spike B showed that the
contract can't be naive: a Claude Code failure arrives as `is_error` with a "success" subtype, auth failures retry
for minutes and look like hangs, and a cancelled run emits no `result` at all. So troupe derives the outcome itself
from the stream and the effect, never from the exit code.

## What Changes

- **A runner contract in `protocol/`:** JSON-RPC 2.0 over stdio, one JSON message per line, defined as JSON
  Schema. A handshake, one run per runner process, a stream of run events (`init` first, then turns, tool calls,
  tool results and retries, then `result`), the native transcript as a separate stream, cancel, shutdown, and
  failures as protocol errors. Vendor-neutral, so Claude Code, a local model and the scripted runner all fit.
- **A runner host in the core:** starts a runner with an explicit environment (never pass-through), performs the
  handshake, supervises the run, enforces every limit as a named setting, cancels gracefully then hard, announces
  silences and retries rather than waiting silently, and derives one outcome per run from the stream, the
  termination and an effect check.
- **Process supervision in the `platform` seam:** starting a runner in its own process group, and killing its
  whole process tree, on Linux, macOS and Windows.
- **A local artifact store:** content-addressed (SHA-256), gitignored, verified on read. The raw transcript (and
  the runner's standard error) go there; the run's outcome references them by hash. The store is a port, so other
  stores can follow (#4 option C).
- **A scripted runner plugin in `plugins/`:** a self-contained package that imports nothing from troupe. It plays
  a script of steps, or replays a recorded protocol stream, and can produce each outcome on demand: success, tool
  calls, an error result, `is_error` with "success", retries, a hang, a cancel honoured or ignored, a missing
  `result`, a crash and a protocol violation.
- **Fixtures with real shapes:** Claude Code stream-json captured from real runs, paired with the protocol events
  it maps to. The failure shapes are captured without credentials; one successful run with tool calls is captured
  by the owner. The Claude Code runner (follow-up) uses the same fixtures as its golden tests.
- **A runner conformance suite:** host-side tests that any runner command can be run against. The scripted runner
  passes it in this change; the Claude Code runner must pass it later.
- The import contract that keeps `plugins/` from importing `troupe`, promised by the bootstrap design (D7.3).

## Capabilities

### New Capabilities
- `runner-protocol`: the language-neutral contract between troupe and an actor runner: framing, handshake, run
  start, the event and transcript streams, cancel, shutdown and errors.
- `actor-runners`: how troupe runs an actor through a runner: launching, supervision, limits and timeouts,
  cancelling, and deriving the run's outcome.
- `artifact-store`: content-addressed storage for large or sensitive run artifacts, such as raw transcripts,
  referenced by hash.
- `scripted-runner`: the deterministic runner plugin used by tests: its script format, replay, and the outcomes it
  can produce on demand.

### Modified Capabilities
- `platform`: adds child process supervision (own process group, the whole tree killed on demand, a minimal
  explicit environment) on all three platforms.

## Impact

- New: `protocol/schemas/runner/` (the contract), `plugins/runner-scripted/` (its own `pyproject.toml`, tests and
  fixtures), `troupe.core.runners` and `troupe.core.artifacts`, `troupe.platform.processes`.
- Changed: `troupe.core.defaults` (runner and store limits), `troupe.core.errors` (new codes),
  `pyproject.toml` (plugins join the workspace, test paths, the plugin import contract), `protocol/README.md`,
  `plugins/README.md`, `docs/platform.md`, and new `docs/runners.md`.
- Dependencies: none at runtime (asyncio and ctypes are standard library). `jsonschema` stays dev-only.
- Out of scope: the Claude Code runner and its opt-in live test (follow-up), a local-model runner (#16, later),
  artifact stores beyond local (#4), container credentials (#11), Docker stages, and recording run events into
  the event store (part C, #33, which wires this change to the event store from #35).
