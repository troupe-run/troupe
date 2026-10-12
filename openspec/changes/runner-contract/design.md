# Design

## Context

See proposal.md for why. What this builds on:

- **The repo today** (bootstrap-repo): `packages/troupe` with `cli` → `core` → `platform` layers enforced by
  import-linter; `troupe.core.defaults` as the one place for limits; `troupe.core.errors` with every error code
  declared in `CODES`; `protocol/schemas/error.schema.json`; `plugins/` holding only a README. Bootstrap design D7.3
  promised the plugin import contract "with the first plugin". This is that plugin.
- **Decision #7:** JSON Schema in `protocol/` is the source of truth. Python types are generated "once there is
  enough schema to justify a generator"; until then, hand-written types are checked against the schema by tests.
- **Decision #16:** the scripted runner comes first; Claude Code is the real runner, exercised by an opt-in live test
  in a follow-up; a local-model runner comes later.
- **Decision #4:** structured events in git, raw transcript out of it, referenced by content hash; the store is
  pluggable, and only the local store is built now.
- **Spike B** (`spike-claude-docker/FINDINGS.md`) found, against real Claude Code 2.1.281:
  - failures report `"subtype": "success"` with `"is_error": true`;
  - a bad credential retries 10 times with backoff and took 188 s to fail; each attempt is a structured
    `system/api_retry` event (`attempt`, `max_retries`, `retry_delay_ms`, `error_status`, `error`);
  - Claude honours SIGTERM but emits no `result` when terminated;
  - single stream-json lines exceed asyncio's 64 KiB default reader limit;
  - killing the local CLI process is not enough to stop a container; the kill must target what actually runs the
    actor;
  - `system/init` is rich (tools, model, MCP servers, permission mode, version) and worth recording first.
- **Parallel work:** the event format is being designed in the event-store change (#35). This change does not
  record anything into the event store; part C (#33) does. What this change assumes about the event format is set
  out in [Assumptions about the event format](#assumptions-about-the-event-format-35).

## Goals / Non-Goals

**Goals:**
- A contract that a runner in any language can implement from the schema and `docs/runners.md` alone.
- One outcome per run, derived by troupe, that cannot be fooled by an exit code or a "success" label.
- Cancel and every timeout behave the same on Linux, macOS and Windows, with OS differences inside `platform`.
- Tests can produce every outcome deterministically, and the shapes they use come from real Claude Code output.
- Nothing in this change constrains the event format #35 chooses.

**Non-Goals:**
- Recording run events into the event store, lineage, identity (part C, #35).
- Choosing which runner an actor uses, or any config for it (the config change). This change takes the runner
  command as an argument.
- Stages and declared-effect enforcement (Docker stages later). The effect check here is a small port with a
  file-based check, not the stage's post-run audit.
- A CLI command. `troupe perform` arrives in part C.

## Decisions

### D1. Framing: JSON-RPC 2.0, one message per line

Each message is one line of UTF-8 JSON ended by `\n`. JSON escapes newlines inside strings, so a message never
contains a raw line feed. Standard output carries only protocol messages; standard error is free-form diagnostics.

- The reader's line limit is a named setting, `RUNNER_MAX_MESSAGE_BYTES` (64 MiB, from spike B's supervisor). A
  longer line is a protocol violation, reported with the limit, never a hang.
- Alternatives considered:
  - `Content-Length` headers (LSP style). More robust for binary payloads, but more work in every language, and
    nothing here is binary. Rejected.
  - Plain JSON Lines without JSON-RPC. Loses request/response correlation and the standard error envelope, which
    cancel and the handshake need. Rejected.
- Precedent: MCP's stdio transport uses the same newline-delimited JSON-RPC, so runner authors are likely to have
  seen it.

### D2. Messages

| Direction | Method | Kind | Purpose |
|---|---|---|---|
| host → runner | `initialize` | request | Offers `protocolVersions: [1]`. Answer: `protocolVersion`, `runner: {name, version}`, `capabilities`. |
| host → runner | `run/start` | request | `runId`, `instructions`, `workspace`, `options` (opaque object), `limits: {eventMaxBytes}`. Answer: `{runId}`. |
| runner → host | `run/event` | notification | One run event (D3). |
| runner → host | `run/transcript` | notification | `{runId, record, encoding?}`: one native record, unchanged. `encoding` is `utf-8` (default) or `base64` for non-text output. |
| host → runner | `run/cancel` | request | Answer: `{}` once the runner has begun stopping. |
| host → runner | `shutdown` | request | After `result`. Answer: `{}`, then the runner exits. |

- **One run per process.** A runner serves one run and exits. That matches how a containerised runner will be
  started (one `docker run` per run), keeps runner state trivial, and makes "kill the process tree" mean "end this
  run". A second `run/start` is an error.
- **`capabilities`** is an object of booleans so later versions can add features (for example, resuming a
  session) without a new protocol version. Version 1 defines none as required.
- **Errors** are JSON-RPC errors whose `data` validates against `error.schema.json`, so a runner's refusal renders
  like any other troupe error. JSON-RPC error `code`s use the standard values (-32600 and so on) plus one
  application code, -32000, for "refused"; the troupe `code` in `data` identifies the reason.
- Files: `protocol/schemas/runner/` holds one schema per message plus `run-event.schema.json` with a `oneOf` over
  the event types. `$id`s follow `https://troupe.run/protocol/runner/<name>.schema.json`.

### D3. Run events: vendor-neutral, summarised, numbered

Every event has `runId`, `seq` (0, 1, 2, …) and `type`. Types and their fields:

| Type | Fields | Notes |
|---|---|---|
| `init` | `runner {name, version}`, `engine? {name, version, model?}`, `tools[]`, `native?` | Always `seq` 0. `native` holds vendor detail, such as Claude's whole `system/init` record. |
| `turn` | `role` (`assistant`, `user`), `text` (summary), `native?` | One per message turn. |
| `tool_call` | `callId`, `tool`, `inputSummary`, `native?` | |
| `tool_result` | `callId`, `isError`, `outputSummary`, `outputBytes` | Full output stays in the transcript. |
| `retry` | `attempt`, `maxAttempts?`, `delayMs`, `reason` (`authentication`, `rate-limit`, `network`, `server`, `other`), `message?` | |
| `log` | `level`, `message` | Runner diagnostics worth keeping with the run. |
| `result` | `status` (`ok`, `error`), `message`, `turns?`, `durationMs?`, `usage?`, `costUsd?`, `native?` | Exactly one, last, unless the run was cancelled or crashed. |
| (host) `oversized` | `originalType`, `bytes`, `ref` | Written by the host in place of an event over `RUN_EVENT_MAX_BYTES` (D8). Never sent by a runner. |

How Claude Code's stream-json maps onto it (the Claude Code runner implements this; the fixtures pin it now):

| stream-json record | Run event |
|---|---|
| `system/init` | `init`; the whole record under `native` |
| `assistant` message | `turn`, plus one `tool_call` per `tool_use` block |
| `user` message with `tool_result` blocks | one `tool_result` per block |
| `system/api_retry` | `retry`; `error: authentication_failed` → `authentication`, 429 → `rate-limit`, connection errors → `network`, 5xx → `server` |
| `result` | `result`; `status` is `error` whenever `is_error` is true, whatever `subtype` says |
| every line | one `run/transcript` record, verbatim |

The mapping is many-to-one per record, but every native line is in the transcript, so nothing the summary leaves
out is lost.

Alternatives considered: passing Claude's stream-json through as the event format. Rejected: it would make the
contract Claude-shaped, which #16's second runner exists to prevent, and it would put full tool outputs (megabytes,
and possibly secrets, #4) into what gets recorded in git.

### D4. Outcome derivation: a pure function

The host collects the facts of a run, then calls one pure function to get the outcome, so every rule is in one
place and is property-tested.

Facts: whether the runner started and completed the handshake; the `result` event if any; whether cancel was
requested and why (caller, run timeout, authentication retry, transcript limit, protocol violation); any protocol
violation; the effect verdict; the exit code (recorded only).

| Facts (first match wins) | Outcome | Error code |
|---|---|---|
| Command could not be started, handshake refused or timed out | `could-not-start` | `runner.start-failed`, `runner.incompatible`, `runner.start-timeout` |
| Protocol violation | `crashed` | `runner.protocol` |
| Cancelled because of an authentication retry | `failed` | `run.authentication` |
| Cancelled because the transcript passed its limit | `failed` | `run.transcript-too-large` |
| `result` with status `error` | `failed` | `run.error-result` |
| `result` with status `ok`, effect check failed | `failed` | `run.effect-missing` |
| `result` with status `ok`, effect check passed | `succeeded` | — |
| No `result`, run timeout expired | `timed-out` | `run.timeout` |
| No `result`, cancelled by the caller | `cancelled` | — |
| No `result`, otherwise | `crashed` | `runner.crashed` |

- **A `result` wins over a later timeout or cancel.** If the runner finished and the timeout fired while it was
  shutting down, the run did finish.
- **The exit code never decides.** A runner that reports `ok`, passes the effect check and exits 1 has `succeeded`,
  with the exit code recorded. This follows #34 and spike B literally. Treating a non-zero exit as a failure would be
  the stricter choice; it is called out in the summary for the owner.
- The outcome is a value (`RunOutcome`) holding the outcome, the error (protocol error shape), the `result` event,
  the exit code, how the runner ended (exited, killed after grace), the transcript and stderr references, and the
  limits in effect.

### D5. Cancel: graceful through the protocol, hard through the platform

1. Send `run/cancel`. This is the graceful path on every OS. A runner that wraps a CLI turns it into whatever its
   child needs (SIGTERM for Claude Code; `docker stop` for a containerised actor, as spike B found).
2. Wait up to `RUNNER_CANCEL_GRACE_SECONDS`.
3. Kill the runner's whole process tree through `platform`.

- **Why not signals for the graceful step:** Windows has no SIGTERM. `CTRL_BREAK_EVENT` reaches only console
  process groups and is unreliable for non-console children. A protocol message works identically everywhere, and
  every runner already reads standard input.
- **Exit on end of input** is the second line of defence: if troupe dies, the runner's standard input closes and the
  runner stops its actor and exits. On Windows the job object (D6) also kills the tree when troupe's handle closes.
- **Shutdown** after a `result` uses the same grace then kill, so a runner that hangs after finishing can't hold the
  run open.

### D6. Platform: child processes

`troupe.platform.processes` gains an async API: start a child with `argv`, `cwd` and an explicit environment;
streams for its standard input, output and error; `wait()`; and `kill_tree()`.

| | Linux and macOS | Windows |
|---|---|---|
| Own group | `start_new_session=True` (a new session and process group) | `CREATE_NEW_PROCESS_GROUP`, and the child is assigned to a new **job object** at once |
| Kill the tree | `os.killpg(pgid, SIGKILL)` | `TerminateJobObject`; the job is created with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, so the tree also dies if troupe does |
| Minimal environment | none: the command is resolved to an absolute path with the caller's `PATH` before starting | `SYSTEMROOT` (Python and Winsock need it), plus the resolved absolute command |
| Long lines | `limit=` on the stream reader, from the caller | same |

- Job objects are reached through `ctypes` (standard library), inside `platform` only. The import contract already
  forbids `signal` outside `platform`; `ctypes` joins that list.
- **Process groups don't survive a `setsid` in a grandchild** on POSIX: a grandchild that starts its own session
  escapes `killpg`. Accepted for now: runners are first-party or reviewed, and Docker stages (later) kill by
  container. Documented in `docs/platform.md`.
- Alternatives considered:
  - `taskkill /T /F` on Windows: walks the parent-pid tree, so it misses re-parented grandchildren. Rejected in
    favour of job objects.
  - `psutil`: a runtime dependency with C extensions for something about 80 lines of `ctypes` covers. Rejected for
    now.

### D7. The run host in the core

`troupe.core.runners` holds:
- `protocol.py`: the hand-written types for the contract (D11);
- `host.py`: `async run_actor(...)`, which takes the runner command, the run request, the artifact store, the effect
  check, the limits, an `on_event` callback and an `on_announce` callback, and returns a `RunOutcome`;
- `outcome.py`: the pure derivation (D4);
- `effects.py`: the effect-check port and its two checks (D10);
- `conformance.py`: the conformance checks (D13).

The host runs three concurrent tasks per run: reading standard output (dispatching events, transcript records and
responses), draining standard error into its artifact, and a watchdog (run timeout, silence announcements, cancel
grace). The API is async because that is how the run server will call it; the CLI (part C) wraps it with
`asyncio.run`.

`on_event` is awaited before the next message is read, so a slow consumer (recording into the event store) applies
back-pressure through the pipe instead of buffering without bound.

### D8. Limits

All in `troupe.core.defaults`, each overridable per run through a `RunLimits` value. There is no `settings`
capability yet, so "policy can only tighten" isn't enforceable here; the config change brings that.

| Setting | Default | Why this value |
|---|---|---|
| `RUNNER_START_TIMEOUT_SECONDS` | 30 | Start-up plus handshake. Python start-up on a cold Windows runner is a few seconds. |
| `RUN_TIMEOUT_SECONDS` | 3600 | One hour per run. Long enough for real coding turns; tests override it. |
| `RUNNER_CANCEL_GRACE_SECONDS` | 10 | Spike B's grace; real Claude stopped well inside it. |
| `RUN_SILENCE_ANNOUNCE_SECONDS` | 30 | Claude's retry backoff reaches about 38 s per step; announce before a person wonders. |
| `RUNNER_MAX_MESSAGE_BYTES` | 64 MiB | Spike B's supervisor limit. |
| `RUN_EVENT_MAX_BYTES` | 64 KiB | Events are destined for git (#4). Larger events go out of line by hash. |
| `RUN_TRANSCRIPT_MAX_BYTES` | 1 GiB | A guard against a runaway runner filling the disk, not an expected size. |
| `RUNNER_STDERR_MAX_BYTES` | 1 MiB | Diagnostics only. Past the limit, stderr keeps its first half and its last half with a marker between, because the end usually explains a failure. |
| `RUNNER_FAIL_FAST_ON_AUTH_RETRY` | true | Spike B: a bad credential otherwise looks like a hang for minutes. |

**Oversized events** are not refused: the host stores the full event in the artifact store and passes on an
`oversized` event with the same `seq`, the original type, the size and the reference. Nothing is lost and the run
continues. The limit is also sent to the runner in `run/start`, so a well-behaved runner summarises below it.

### D9. Transcripts

- The transcript artifact is the run's `run/transcript` records in order, each followed by `\n`. `utf-8` records are
  written as their UTF-8 bytes; `base64` records are decoded first. For Claude Code this reproduces its stream-json
  output byte for byte.
- It is written as the run goes, through the store's streaming writer, so a crashed or cancelled run still keeps
  everything received (finalised in the host's `finally`).
- Standard error is a second artifact. An empty stream still gets a reference, so the outcome's shape never varies.
- The outcome carries `transcript` and `stderr` as `sha256:<hex>` references.

### D10. Artifact store and effect check

**Store:** a port (`ArtifactStore`: `open_writer()` → writer with `write(bytes)`, `finish() -> ref`, `abort()`;
`read(ref) -> bytes`; `open_reader(ref)`; `contains(ref)`), with `LocalArtifactStore(root)` and an in-memory store
for tests.

- Layout: `<root>/sha256/<first two hex>/<hex>`. A writer streams into `<root>/tmp/<random>` while hashing, fsyncs,
  then moves the file to its final name. If the final name already exists, the same bytes are already stored, so the
  temporary file is deleted (deduplication without a race).
- The move uses `platform` (a new `commit_file(temp, target)` beside the existing atomic replace), so the Windows
  in-use retry and the POSIX directory fsync are reused.
- **Out of git without touching user files:** on first use the store writes `<root>/.gitignore` containing `*`. Git
  then ignores the whole directory, including that file, and the theatre's own `.gitignore` is never edited. This
  also means the event-store change doesn't need to coordinate a `.gitignore` entry for it.
- Reads stream the file through SHA-256 and raise `artifact.corrupt` on a mismatch; a missing reference raises
  `artifact.missing`.
- Leftover temporary files from a killed process stay in `<root>/tmp/`. Cleaning them is safe only when no writer is
  live, so it is left to a later `troupe` maintenance command and noted in the docs.
- Location: the caller passes the root. Part C will use `.troupe/artifacts/` in the theatre. The store is addressed
  by hash, not path, so a hosted store can replace it (#4 option C) without changing callers.

**Effect check:** a port (`EffectCheck`: `before()` at run start, `after() -> EffectVerdict`), with:
- `NoEffectExpected`: always passes. It must be chosen explicitly; there is no default, so a caller can't forget
  the check.
- `ExpectedFiles(paths)`: each path must exist after the run and its SHA-256 must differ from before the run (or the
  file must be new).

Stages bring the real post-run audit (spike B: a diff of the declared write paths) later; they implement the same
port.

### D11. Python types: hand-written, checked against the schema

The contract adds about a dozen definitions. #7 says to generate Python types once there is "enough schema". The
generator choice (and whether its output needs a runtime dependency such as pydantic) affects every later schema,
and the config change will bring far more schema than this one, so the generator is chosen there.

Until then, the types in `troupe.core.runners.protocol` are frozen dataclasses with `to_data()`/`from_data()`, and
tests validate every message both sides produce against the schema, including hypothesis-generated events. The
scripted runner has its own small copy of the types, because it may not import troupe; its tests validate against
the same schema files.

### D12. The scripted runner

- **Package:** `plugins/runner-scripted/`, distribution `troupe-runner-scripted`, module `troupe_runner_scripted`,
  run as `python -m troupe_runner_scripted`. Standard library only.
- **Workspace:** `plugins/*` joins the uv workspace members, so `scripts/check.py` lints, type-checks and tests it
  with everything else. It keeps its own `pyproject.toml` and `tests/`, so it can still move to its own repository
  with `git filter-repo`.
- **Import contract:** import-linter `forbidden`, source `troupe_runner_scripted`, forbidden `troupe`.
- **Concurrency:** a reader thread on standard input feeds a queue; the main thread plays the script. Threads avoid
  asyncio's awkward stdin pipes on Windows, and let a `wait` or `hang` step wake at once on `run/cancel` or end of
  input.
- **Script format** (JSON, in `options.script` inline or `options.scriptPath`):

  ```json
  {"onCancel": "honour", "steps": [
    {"event": {"type": "init", "runner": {"name": "scripted", "version": "0.1.0"}, "tools": ["Write"]}},
    {"transcript": "{\"type\":\"system\",\"subtype\":\"init\"}"},
    {"wait": {"ms": 50}},
    {"writeFile": {"path": "out/hello.txt", "content": "hi"}},
    {"event": {"type": "result", "status": "ok", "message": "done"}}
  ]}
  ```

  | Step | Effect |
  |---|---|
  | `event` | Sends a run event; `seq` and `runId` are filled in unless the step sets them (for violations). |
  | `transcript` | Sends a transcript record. |
  | `stderr` | Writes text to standard error. |
  | `wait` | Sleeps, waking early on cancel or end of input. |
  | `writeFile` | Writes a file under the workspace (refuses paths outside it). |
  | `hang` | Blocks until cancel or end of input. |
  | `exit` | Exits with a code, at once. |
  | `rawStdout` | Writes an arbitrary line to standard output, for protocol-violation tests. |
  | `replay` | Plays a recording (D14) in place of this step. |

  `onCancel`: `honour` (acknowledge, exit without a `result`, like Claude Code), `honour-with-result` (acknowledge,
  send `result` with status `error`, exit), or `ignore` (acknowledge, carry on; only a kill stops it).
- Timing in scripts is real time, kept to milliseconds in tests. Every host limit is overridable, so tests run with
  sub-second timeouts.

### D13. Conformance suite

`troupe.core.runners.conformance` holds checks that any runner must pass with a trivial run: the handshake and
version refusal, `init` at `seq` 0, gap-free `seq`, schema-valid messages, one `result` then `shutdown`, refusal of a
second `run/start`, acknowledging `run/cancel` and exiting, and exiting on end of input. The checks take the runner
command and the `run/start` options that make it do a short run, so they work for runners whose behaviour can't be
scripted (Claude Code supplies a cheap prompt). The tests run them against the scripted runner; an environment
variable, `TROUPE_CONFORMANCE_RUNNER`, points them at another runner command.

### D14. Fixtures from real Claude Code output

- **Format:** a recording is JSON Lines; each line is either `{"transcript": "<native line>"}` or
  `{"event": {...}}`, interleaved in the order a runner would send them. Each fixture directory holds
  `recording.jsonl`, `provenance.json` (Claude Code version, date, command, environment, scrubbing applied) and
  `expected.json` (the outcome the host must derive).
- **Native lines are captured; events are written by hand.** The capture tool (`plugins/runner-scripted/tools/
  capture_claude.py`, not run in CI) records Claude's stream-json and the provenance. The paired events are written
  and reviewed by hand, because generating them would mean writing the Claude Code runner's mapping now. The Claude
  Code runner's golden test will then be: its mapping of each fixture's native lines equals the fixture's events.
- **Captured without credentials** (spike B's method: an isolated `CLAUDE_CONFIG_DIR`, a deliberately invalid API
  key, `--bare`, the API unreachable or a local fake endpoint, a temporary workspace):
  - `is-error-success-subtype`: `init` then a `result` with `subtype: success` and `is_error: true`;
  - `auth-retries`: `init`, `api_retry` events with `authentication_failed`, then the error `result`;
  - `terminated-no-result`: `init` and retries, then SIGTERM during backoff; no `result`.
- **Captured by the owner** (needs a real credential, which never enters an agent session, as in spike B's
  addendum): `success-with-tools`, one short run with a pinned `--model` and `--max-budget-usd 0.10` that writes a
  file and reads it back. Expected cost is about $0.03.
- **Scrubbing** replaces the temporary workspace with `/workspace`, the session id and UUIDs with fixed values, and
  the user's home with `~`. A test scans every fixture for credential patterns (`sk-ant-`, `Bearer `, OAuth token
  prefixes) and for home-directory paths (`/Users/`, `/home/`, `C:\Users\`) and fails naming the fixture and line.

### D15. Error codes

Added to `CODES`, all `ExitCode.FAILURE`: `runner.start-failed`, `runner.incompatible`, `runner.start-timeout`,
`runner.protocol`, `runner.crashed`, `run.error-result`, `run.effect-missing`, `run.timeout`, `run.authentication`,
`run.transcript-too-large`, `artifact.missing`, `artifact.corrupt`, `artifact.write-failed`.

## Assumptions about the event format (#35)

The event-store change is designing the event format in parallel. This change records nothing into the event store
and imports nothing from it. Part C maps run events to domain events. These are the assumptions this change makes,
so #35 can check them; if one is wrong, what changes is listed with it.

1. **Run events are not event-store events.** The protocol's run events are the runner's report. Part C turns them
   into domain events (for example, one per run event, plus run started and run ended) in whatever format #35
   defines. *If wrong:* nothing here changes; only C's mapping does.
2. **Events are JSON objects stored one per line.** Run events are JSON objects with no line feeds when serialised,
   and each is capped at `RUN_EVENT_MAX_BYTES` (64 KiB). Anything larger is stored out of line and referenced by
   hash. *If #35 sets a lower per-event size:* lower the default; the mechanism stays.
3. **Lineage is added by troupe, never by the runner.** The runner is untrusted and supplies no actor, via, time,
   reason, change id or approvals. C sets the actor to the agent being run (kind `agent`, never null), `via` to the
   runner's name and version from `init`, and the time to when the host received the event. Any time inside a run
   event is data, not lineage. *If #35 expects the producer to supply lineage:* C supplies it; the protocol stays.
4. **Content-hash IDs that leave out wall time and actor** don't collide across runs, because every run event carries
   its `runId` and `seq`. The same run event recorded twice hashes the same, which makes recording idempotent.
   *Assumes:* the hash covers the payload, and the payload includes the run id.
5. **One stream per run fits.** A run's events have a dense, gap-free `seq` starting at 0, which maps onto
   `originator_version` if #35 makes each run its own stream (the run id as originator id). A repeated `seq` is
   already a protocol violation here, matching the library's `IntegrityError` on a duplicate version. *If #35 uses a
   different stream layout:* `seq` is still the in-run order; nothing here relies on notification ids.
6. **Artifacts are referenced as strings.** References are `sha256:<64 hex>`; the event store needs no binary or
   attachment support. *If #35 wants a structured reference:* C wraps the string.
7. **VCS state is C's job.** Branch, HEAD and file hashes are recorded by C, not reported by the runner.
8. **`init` is recorded first** (#4). The host guarantees `init` is the first run event, so C can record it first
   without reordering.
9. **The run id is minted by the caller** (C), as a unique string. This change only checks it is a non-empty string
   of at most 128 characters from `[A-Za-z0-9._-]`. *If #35 standardises an id format (UUID, ULID):* tighten the
   check in the schema.

## Risks / Trade-offs

- [Windows job objects through `ctypes` are fiddly, and there's a short window between starting the child and
  assigning it to the job in which a grandchild could escape] → The runner is the only child, and it starts nothing
  before reading `initialize`; the test kills a tree with a grandchild on all three OSes in CI. Starting the child
  suspended and resuming it after assignment closes the window and is noted as the fix if CI ever shows a leak.
- [Claude Code's stream-json format drifts] → Each fixture records the Claude Code version. The follow-up Claude Code
  runner's opt-in live test catches drift against the current version.
- [Hand-written types drift from the schema] → Every message both sides produce is validated against the schema in
  tests, including generated ones. The generator decision is taken in the config change (D11).
- [`success` with a non-zero exit code] → Follows the spike's rule that the exit code isn't evidence. Flagged for the
  owner; changing it is one row of D4.
- [The owner's capture of a successful run is a manual step] → It's one short run at about $0.03, scripted end to
  end. The credential-free fixtures don't depend on it, so implementation isn't blocked while it waits.
- [Timing-based tests are flaky on slow CI runners, especially Windows] → Tests use the scripted runner's explicit
  `hang` and `wait` steps and assert on order and outcome, not on durations; timeouts in tests are set with a margin
  and never asserted to the millisecond.
- [A grandchild that calls `setsid` escapes `killpg` on POSIX] → Documented limitation (D6). Containerised runners
  are killed by container.

## Migration Plan

None: this adds new capabilities and changes no existing behaviour. Rollback is reverting the change.

## Open Questions

- The default values in D8 are first estimates. They can be tuned without changing the specs, because each is a
  named setting.
