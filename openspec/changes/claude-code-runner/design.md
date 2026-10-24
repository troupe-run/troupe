# Design

## Context

See proposal.md for why. What exists today:

- **The runner contract** (`contributing/runners.md`, `protocol/schemas/runner/`) includes the "Mapping an engine:
  Claude Code" table. The host (`troupe.core.runners.host.run_actor`) does the following:
  - checks every message;
  - announces silences and retries;
  - cancels at once on an authentication retry (`RUNNER_FAIL_FAST_ON_AUTH_RETRY`);
  - gives a runner `RUNNER_CANCEL_GRACE_SECONDS` after `run/cancel` or `shutdown`, then kills its process tree. On
    POSIX that's the runner's process group, and on Windows its job.
  - accepts `run/transcript` at any time, and refuses an event after the `result`.
- **The host kills the tree only while the runner is running.** On POSIX, a child the runner leaves behind after
  exiting cleanly isn't killed (`host.kill` checks `returncode`). On Windows, releasing the job kills whatever is left.
  So on POSIX the runner itself must make sure Claude Code has ended.
- **The scripted runner** (`plugins/runner-scripted/`) is the pattern to follow. It uses only the standard library and
  imports nothing from troupe (an import-linter contract checks this). A reader thread feeds a queue, and its schemas
  are published inside its package. Its `fixtures/claude-code/` holds four recordings, each pairing scrubbed native
  lines with hand-written events, plus `expected.json` and `provenance.json`, and `tools/capture_claude.py` captures
  them. `packages/troupe/tests/test_claude_fixtures.py` replays them through the host.
- **`perform`** resolves the runner's name through `troupe.core.interim.RUNNERS`, which knows only `scripted`. It
  starts the runner with `RunnerCommand(argv, cwd=workspace)` and no `env`. Under `RUNNER_ENVIRONMENT` the runner
  gets only the platform minimum (`SYSTEMROOT` on Windows). Config checks an actor's options against the schema of
  the runner it names, through the same table.
- **What the real CLI does (2.1.302, checked offline while drafting):**
  - `claude -p` with no prompt argument reads the prompt from standard input;
  - a refused connection retries as `"error":"unknown","error_status":null`, and its result is `is_error` under
    `"subtype":"success"`;
  - an isolated run (`--setting-sources ""`, no `--bare`) reports `permissionMode: "default"`. The fixtures' `"auto"`
    comes from `--bare`;
  - `--bare` never reads OAuth or the keychain;
  - the permission modes are `acceptEdits`, `auto`, `bypassPermissions`, `manual`, `dontAsk` and `plan`, and the
    setting sources are `user`, `project` and `local`.
- **The fixtures disagree with the contract in one place.** `success-with-tools`'s `result` leaves out
  `cacheReadTokens` and `cacheWriteTokens`, although its native record has them and the contract's table maps them.
  The events were written before 613ca5b added the four counters, and that commit only removed `native` from them.

## Goals / Non-Goals

**Goals:**
- **The mapping the fixture tests check is the mapping the runner runs:** one pure, line-at-a-time mapper with no I/O,
  used by both.
- **Nothing from troupe or config is parsed by a shell, on any platform.** The direction, the character and the tool
  rules never appear on Claude Code's command line.
- **The runner never outlives Claude Code, and Claude Code never outlives the runner,** on all three operating
  systems.
- **A run doesn't depend on whose machine it's on**, apart from the login.

**Non-Goals:**
- Streaming input (`--input-format stream-json`), multi-turn runs and resuming sessions. A run is one direction and
  one result.
- Partial messages (`--include-partial-messages`). Turns are reported when complete.
- Recording in lineage which variables reached the runner. The names are fixed in one table today. Recording them
  belongs with config naming runners (#38).
- Checking Claude Code's version against a minimum. A format change shows up as `debug` logs and fixture drift
  (D5), not as a refusal.
- Sharing the JSON-RPC framing code with the scripted runner. Each plugin stays self-contained so it can be split
  out, so the framing is duplicated, at around 150 lines.

## Decisions

### D1. Plugin layout: one module per concern, with one OS seam

`plugins/runner-claude-code/src/troupe_runner_claude_code/`:

| Module | What it holds |
|---|---|
| `__init__.py` | `NAME = "claude-code"`, `__version__` |
| `defaults.py` | Every limit the runner has, each a named constant (D11) |
| `options.py` | Parsing and checking the options into a frozen `Options`, raising `OptionsError(code, where, problem, fix)` |
| `command.py` | Building Claude Code's command line and its private files from `Options`, the character and a temporary directory (D3) |
| `mapping.py` | `Mapper`: one native line in, a list of transcript records and events out. Pure, with no I/O (D5) |
| `processes.py` | **The only module that imports `signal` or branches on `os.name`**: start, stop, kill, wait (D6) |
| `runner.py` | The JSON-RPC loop, the threads and the run's lifecycle (D2, D7) |
| `schemas/` | `options.schema.json` and `errors.schema.json` (D10) |

The import-linter configuration gains `troupe_runner_claude_code` in `root_packages`, in the source modules of
`plugins import nothing from troupe`, and in a new contract: only `troupe_runner_claude_code.processes` imports
`signal`, `ctypes`, `msvcrt` or `_winapi`. That keeps the constraint "OS-specific behaviour behind one named seam"
inside the plugin, which can't use `troupe.platform`.

*Alternative:* one module, as the scripted runner nearly is. Rejected: the mapper has to be testable without a
process (D5), and the OS seam has to be checkable.

### D2. Threads and one queue, as in the scripted runner

Three daemon threads feed one `queue.Queue` of tagged items, and the main thread is the only one that writes to
standard output:
- troupe's lines, then `EOF`;
- Claude Code's stdout lines, then `ENGINE_EOF`;
- a thread that copies Claude Code's stderr to the runner's stderr byte for byte, writing nothing to the queue.

Every state change happens on the main thread, so a cancel arriving mid-line is handled between two lines and never
inside one. Lines are read as bytes with no size limit of the runner's own: troupe's `RUNNER_MAX_MESSAGE_BYTES` bounds
what the runner sends, and a record over it becomes troupe's protocol violation, named by troupe.

*Alternative:* asyncio subprocesses. Rejected: Windows needs the proactor loop for pipes, the scripted runner's
thread-and-queue design is already proven on all three CI platforms, and the runner has no concurrency beyond these
three streams.

### D3. Claude Code's command line holds only fixed flags, numbers, the model and private file paths

```
claude -p --output-format stream-json --verbose --no-session-persistence
       --setting-sources <"" | user,project,local subset> --strict-mcp-config
       --max-budget-usd <n> [--model <m>] [--permission-mode <mode>]
       [--append-system-prompt-file <tmp>/character.md] [--settings <tmp>/settings.json]
```

- **The direction goes on standard input as UTF-8, and then standard input is closed.** This avoids:
  - Windows' 32,767-character command-line limit;
  - process listings, where any user on the machine can read a command line;
  - `cmd.exe` re-parsing the command line when `claude` is an npm `.cmd` shim.
- **The character goes to `--append-system-prompt-file`.** Appending keeps Claude Code's own system prompt, which
  carries its tool instructions. Replacing it (`--system-prompt-file`) would break the tools and isn't asked for.
- **`allowedTools` and `disallowedTools` go in a settings file**, as `{"permissions": {"allow": [...], "deny":
  [...]}}`, passed with `--settings`. Rules like `Bash(git *)` hold spaces and `cmd.exe` metacharacters. The file is
  written only when either option is set.
- **The private files live in `tempfile.mkdtemp(prefix="troupe-claude-code-")`,** outside the workspace, so the effect
  check and the run's diff never see them. Its permissions are 0700 on POSIX. The runner removes the directory when
  it exits, on every path.
- **`model` must be non-empty, have no control characters and not start with `-`**, so Claude Code's own parser can't
  read it as a flag. `maxBudgetUsd` is written with `repr(float)`.
- **Claude Code's environment is the runner's own** (D8), plus `DISABLE_AUTOUPDATER=1` and
  `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`, so a run doesn't update the CLI or send telemetry. Neither variable
  touches the login.

*Alternatives:*
- `--input-format stream-json`, which sends the direction as a user message. It does the same job with one more
  format to keep in step with, and it's only needed for multi-turn runs, a non-goal.
- The prompt as an argument. Rejected for the three reasons above.

### D4. Isolated from the person's and the workspace's settings by default, with `settingSources` to opt in

`--setting-sources ""` and `--strict-mcp-config` are the default (owner, 2026-10-24). An isolated run loads none of
these:
- the person's `~/.claude/settings.json` hooks, permissions and default mode;
- the workspace's `.claude/settings.json`. In a worktree of this repository, that would run its guard hooks inside
  the actor;
- MCP servers.

Login isn't a setting, so it still works. `settingSources: ["project"]` (any subset of `user`, `project` and `local`,
with no repeats) restores the sources named. `--bare` is never used: it blocks OAuth and the keychain, and the issue
requires the person's existing login.

Whether `CLAUDE.md` files load under `--setting-sources ""` isn't documented. The live test records it in its output
rather than asserting it, and the README says so. That's an open question, below.

### D5. The mapping is a pure, stateful `Mapper`, and the fixtures drive it

`Mapper(runner_version, event_max_bytes)` has one method, `feed(line: bytes) -> list[Out]`. Each `Out` is
`Transcript(record, encoding)` or `Event(dict)`, and the event has no `runId` or `seq`. The runner numbers events as it
sends them, as the contract requires. For every line, the first `Out` is the line's own transcript record, so the
transcript stays complete and in order even when mapping fails. The mapper's state:
- whether `init` was sent;
- the tool-call ids seen;
- the record types it has already noted;
- whether a `result` was sent. After one, it maps lines to transcript records only.

The mapping, beyond the contract's table:

| Native | Events |
|---|---|
| `system/init` | `init`: runner `claude-code` and `__version__`; `tools`; engine `{name: "claude-code", version: claude_code_version, model}`, leaving out any engine field the record lacks |
| any event-producing line before `system/init` | first a synthetic `init` with no `engine` and `tools: []` |
| `assistant` | `turn` (the text blocks joined with `\n`, sent only if non-empty), then a `tool_call` per `tool_use`, with `inputSummary` the compact JSON of `input`. `thinking` and other blocks are transcript only. `parent_tool_use_id` (a subagent's messages) is mapped the same way: the contract has no nesting |
| `user` | a `tool_result` per `tool_result` block. The text is the content string, or a list's `text` blocks joined with `\n`. Each non-text block counts as its compact JSON's bytes. `outputBytes` is the UTF-8 length. For an unknown `tool_use_id`, a `log` warning (the host would refuse the pair) |
| `system/api_retry` | `retry`. The reason, taking the first rule that matches: `error == "authentication_failed"` → `authentication`; status 429 → `rate-limit`; status 500–599 → `server`; status null → `network`; else `other`. `message` is `"<error> (HTTP <status>)"` or `"<error> (no HTTP response)"`. `maxAttempts` is sent only when `max_retries` is a positive integer |
| `rate_limit_event` | none while `allowed`; otherwise `log` warning `"rate limit <status> (<rateLimitType>)"` |
| `result` | a `log` warning per denied tool (from `permission_denials[].tool_name`, counted: `"permissions denied Write ×2"`), then `result`. `status` is `error` if `is_error` or `subtype != "success"`. `message` is `result` if it's a non-empty string, else the subtype. `turns`, `durationMs`, `usage` (only counters present and integral) and `costUsd` (only when numeric) |
| `result` that isn't an object with a boolean `is_error` and a string `subtype` | `log` error naming what's missing; no `result` (D7) |
| a type or `system` subtype not named here | the first time in the run: `log` debug `"Claude Code record type <t> isn't mapped"`. Nothing after that |
| not a JSON object | `log` warning `"Claude Code wrote a line that isn't a JSON object"`. Sent as a `base64` transcript record if it isn't UTF-8 |
| a known type missing the fields its mapping needs | `log` error naming the type and the field; no other event |

JSON is parsed strictly: duplicate keys, `NaN` and `Infinity` are refused. A line refused that way is "not a JSON
object" for the mapping, and stays verbatim in the transcript.

**Summaries (D11):** each summary field is cut to `SUMMARY_MAX_BYTES`, on a UTF-8 boundary, with the suffix
`" … [<n> bytes left out]"`. If the serialised event still exceeds `event_max_bytes`, the field is cut again to fit,
with headroom for the suffix. `outputBytes` always counts the whole output.

**The fixtures are corrected to the contract,** which wins: the fixtures exist to pin it. `success-with-tools`'s
`result` gains `"cacheReadTokens": 42158, "cacheWriteTokens": 5737`, and the error fixtures gain their zero counters.
Each correction goes in its own commit, with the reason. The scripted replay's outcomes don't change.

*Alternative:* generate the fixtures' events with the mapper. Rejected: the hand-written, reviewed events are the
independent check. If the mapper wrote them, the test would compare the mapper with itself.

### D6. Stopping Claude Code: SIGTERM on POSIX, terminate on Windows, then kill; same process group

`processes.start` runs `claude` in the runner's own process group on POSIX (no `start_new_session`), so troupe's
group kill reaches it if the runner is itself killed. On Windows it stays in the runner's job, so closing the job
kills it.

`processes.stop(proc, grace)` sends a polite stop, waits up to `grace`, then kills, and returns the exit code:
- **On POSIX**, SIGTERM and then SIGKILL. The `terminated-no-result` fixture shows Claude Code exits 143 on SIGTERM,
  with no `result`.
- **On Windows**, `Popen.terminate()` (`TerminateProcess`) at once. A console control event would need
  `CREATE_NEW_PROCESS_GROUP` and a shared console, and the runner, started by troupe with
  `CREATE_NEW_PROCESS_GROUP`, has no reliable console to share. Claude Code's own children are in the runner's job,
  and die when troupe releases it.

`CLAUDE_STOP_GRACE_SECONDS = 5` is below the host's `RUNNER_CANCEL_GRACE_SECONDS` default of 10, so the runner
normally finishes its own stop before troupe kills it.

On `run/cancel`, the runner:
1. answers `{}`;
2. tells the mapper to send no more events (transcript records still go, so nothing Claude Code writes while it
   stops is lost);
3. stops Claude Code;
4. drains its stdout to EOF;
5. exits with code 0.

Exiting 0 is safe: a run with no `result` can't succeed, and the host records `cancelled`. End of input does the
same, with no answer to send.

*Alternative:* `CTRL_BREAK_EVENT` on Windows, for a graceful stop. Rejected for now: it isn't reliable without a
console, and nothing in the contract needs a graceful stop. Claude Code sends no `result` after a stop on any
platform.

### D7. The run's lifecycle and the runner's exit code

```
handshake ─▶ run/start ──refused──▶ error answer; stays up for another run/start or shutdown
                  │ ok: answer {runId}, then start claude (start failure: init, log error, exit 1)
                  ▼
             streaming ── result record ──▶ result sent ─▶ wait for claude to exit (CLAUDE_EXIT_WAIT_SECONDS,
                  │                                         then stop it) ─▶ answer shutdown ─▶ exit
                  ├─ ENGINE_EOF, no result ─▶ wait for exit ─▶ (init and log error if no init yet) ─▶ exit non-zero
                  └─ run/cancel or EOF ─▶ D6
```

- **Checks that can fail run before `run/start` is answered:** the options are checked, `claude` is found on `PATH`,
  and the temporary directory is made. Each failure is refused in the answer, with a `claude-code.*` code, and the
  host records `could-not-start`. A failure to *start* the process found (`OSError`) can only happen after the
  answer. It becomes `init` (no engine), then a `log` error, then exit 1, which the host records as `crashed`. Starting
  the process before answering was considered, and rejected: Claude Code would begin working before troupe knows the
  run started.
- **If Claude Code ends without a `result`,** the runner writes `claude-code runner: Claude Code exited with code N
  and sent no result` to stderr. It sends no event: the contract's outcome table already says what a missing result
  means. Then it exits with Claude Code's code mapped as below. This is the `terminated-no-result` path. When Claude
  Code ends before its init record, the runner waits for its exit code, then sends the synthetic `init` and a `log`
  error naming that code, so `perform` can show why the run went nowhere.
- **The exit code:** 0 if Claude Code exited 0. Otherwise its code if it's 1–255; 128+n for POSIX signal n; and 1 for
  anything else (Windows' larger codes). The exact code always goes to stderr.
- **After `result`, troupe's `shutdown` is answered only once Claude Code has exited,** or after
  `CLAUDE_EXIT_WAIT_SECONDS` (5) and a stop. Then the runner exits with the mapped code. A non-zero code after an ok
  result is the host's `run.unclean-exit`, which is right: Claude Code ended in a way nobody vouches for.

### D8. The interim table names each runner's environment; `perform` copies those names from its own

`interim.Runner` gains `environment: tuple[str, ...]`, the names `perform` copies from its own environment into
`RunnerCommand.env`, each only when set. The table stays the one place where a runner's name becomes a process.
`scripted` gets `()`, so nothing changes for it. `claude-code` gets these names:

| Why | Names |
|---|---|
| Find `claude` and run its tools | `PATH`, plus `PATHEXT` and `COMSPEC` on Windows |
| Find the login and config | `HOME`, `USER`, `LOGNAME`, `USERPROFILE`, `HOMEDRIVE`, `HOMEPATH`, `USERNAME`, `APPDATA`, `LOCALAPPDATA`, `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_CACHE_HOME`, `XDG_RUNTIME_DIR`, `CLAUDE_CONFIG_DIR` |
| Credentials named in #55 | `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_API_KEY` |
| Temporary files | `TMPDIR`, `TEMP`, `TMP` |
| Text and locale | `LANG`, `LC_ALL`, `LC_CTYPE` |
| Networks behind a proxy | `HTTPS_PROXY`, `HTTP_PROXY`, `NO_PROXY` and their lower-case forms, `NODE_EXTRA_CA_CERTS` |

The table holds the list once. A test checks that `perform` passes exactly the names that are set and nothing else
(spec: runs). On Windows the names are matched case-insensitively, as `EnvironmentPolicy` already does.

*Alternatives:*
- The runner asks for variables in its `initialize` answer. Rejected: the process has already started by then,
  without them, and the contract would grow a field for one runner.
- A permissive `EnvironmentPolicy` for runners. Rejected: it changes the default for every runner, and decision D6
  of the actor-runner design chose "nothing unless named".
- Copying troupe's whole environment. Rejected for the same reason: secrets like `AWS_SECRET_ACCESS_KEY` would reach
  every actor.

### D9. Finding `claude`: `shutil.which` on the runner's own `PATH`, never an option

The interim table's rule is that no request or config file carries a program to run, and the runner keeps that rule.
It resolves `claude` with `shutil.which("claude", path=os.environ.get("PATH"))`, which applies `PATHEXT` on Windows,
so an npm `claude.cmd` or a native `claude.exe` is found. It writes the resolved path to stderr. A `.cmd` shim is safe
to run because of D3: no free text goes on its command line, and the paths are the runner's own temporary files.

The tests put a stand-in `claude` first on `PATH`: an executable Python script on POSIX, and a `claude.cmd` calling
`python fake_claude.py %*` on Windows. The perform test sets `PATH` in `perform`'s environment, so it also proves that
D8 delivers `PATH`.

### D10. Options and errors: schema-published and code-checked, kept in agreement by tests

`options.schema.json` is closed (`additionalProperties: false`):

| Option | Rule |
|---|---|
| `model` | a string, at least one character, matching `^[^-\x00-\x1f\x7f][^\x00-\x1f\x7f]*$` |
| `maxBudgetUsd` | a number with `exclusiveMinimum: 0` |
| `permissionMode` | one of `acceptEdits`, `auto`, `bypassPermissions`, `manual`, `dontAsk` or `plan` (Claude Code 2.1.302's choices) |
| `allowedTools`, `disallowedTools` | arrays of non-empty strings without control characters, `uniqueItems` |
| `settingSources` | an array of `user`, `project` and `local`, `uniqueItems` |

`errors.schema.json` defines four codes, each with `details`:

| Code | `details` |
|---|---|
| `claude-code.unknown-option` | `{where}` |
| `claude-code.invalid-options` | `{where}` |
| `claude-code.not-found` | `{path}`, the `PATH` searched |
| `claude-code.start-failed` | `{where}`, naming the temporary directory |

`options.py` checks the same rules in code, because the plugin uses only the standard library and has no
`jsonschema`. The plugin's schema test (as `test_scripted_schemas.py` does) checks two things: every options value the
code accepts or refuses is accepted or refused by the schema too, and every error the runner sends validates against
the bound schema. A hypothesis test generates options and compares the code's verdict with the schema's, so the two
can't drift apart.

`bypassPermissions` is allowed. The local stage is already unenforced, and policy admits it explicitly. A policy
rule restricting permission modes can come with policy work.

### D11. The runner's limits are named in `defaults.py`

| Setting | Default | What it limits |
|---|---|---|
| `DEFAULT_MAX_BUDGET_USD` | `5.0` | A run's spend when `maxBudgetUsd` isn't set (owner, 2026-10-24) |
| `SUMMARY_MAX_BYTES` | `4096` | One summary field in an event, before `eventMaxBytes` |
| `CLAUDE_STOP_GRACE_SECONDS` | `5.0` | How long Claude Code has to exit after SIGTERM before it's killed |
| `CLAUDE_EXIT_WAIT_SECONDS` | `5.0` | How long the runner waits for Claude Code to exit after its `result` before stopping it |

Each limit is documented in the plugin's README. troupe's limits (`contributing/runners.md`) are unchanged.

### D12. Tests: the plugin's own, core's through the host, and the opt-in live test

Like the scripted runner's, the plugin's tests import nothing from troupe. They speak the protocol through their own
harness, which validates every message against the bound schemas. Tests that need the host's outcomes live in
`packages/troupe/tests/`, which already reads the plugin's files by path.

1. **The mapper, in the plugin, offline and fast** (`test_mapping.py`):
   - each fixture's native lines go through `Mapper`, and the transcript records and events must equal the
     recording's, in order. The runner version is the fixture's `unreleased`;
   - a scenario-per-row test of the table in D5;
   - a hypothesis property: arbitrary lines (random bytes, random JSON, and mutated fixture records) never raise.
     Every event validates against `run-event.schema.json` once numbered, every `tool_result` follows its
     `tool_call`, no event follows `result`, and every event fits `event_max_bytes`.
2. **The runner process, in the plugin, with the stand-in `claude`** (`test_runner.py`, `fake_claude.py`,
   `claude_harness.py`):
   - the stand-in records its command line, its stdin and its environment to a file, then replays a fixture's native
     lines (`FAKE_CLAUDE_FIXTURE`, `FAKE_CLAUDE_EXIT`, `FAKE_CLAUDE_HANG`);
   - it handles SIGTERM by exiting 143 with no `result`, as the real CLI does;
   - the tests cover the handshake, refusals, the command line, the stdin and the private files from D3, the
     exit-code mapping, and cancel and end of input, where the stand-in's pid must be gone before the runner exits,
     on all three operating systems.
3. **Through the host, in core** (`packages/troupe/tests/test_claude_code_runner.py`):
   - each fixture played by the stand-in through `run_actor`, with fail-fast on and off, must give the outcome in
     `expected.json`;
   - a cancel must end `cancelled`;
   - an ok result followed by exit 1 must end `run.unclean-exit`.

   `test_runner_conformance.py` gains a case for the Claude Code runner, with the stand-in on `PATH`, and
   `test_interim.py` gains one resolving `claude-code` to a runner that passes it.
4. **Perform, end to end, in core** (`test_perform_claude_code.py`): a theatre with a `claude-code` actor, the
   stand-in on `PATH`, and a secret variable set. The test checks the outcome `succeeded`, the recorded `init` engine,
   and that the stand-in's recorded environment has `PATH` and the credential but not the secret.
5. **Live, in core** (`test_claude_code_live.py`): skipped unless `TROUPE_LIVE_CLAUDE_CODE=1`, with a message naming
   the variable. It uses the pinned model `claude-haiku-5-5`, a budget of `0.10`, the capture tool's prompt,
   `allowedTools: ["Write", "Read"]` and no `permissionMode`, so a pass also proves the settings file's allow rules
   apply under `--setting-sources ""`. It runs through `run_actor` and asserts:
   - the outcome is `succeeded`;
   - `out/hello.txt` holds `hi`;
   - a `tool_call` for `Write`;
   - `costUsd` ≤ 0.10.

   It uses `CLAUDE_CODE_OAUTH_TOKEN` or `ANTHROPIC_API_KEY` when set, and otherwise the person's login, by passing
   `HOME` and the D8 names. It prints which, and whether `CLAUDE.md` loaded (D4). CI never sets the variable. The
   owner runs it, never an agent session, as with the success fixture.

### D13. Fixtures move with the capture tool, and three are added offline

`git mv` moves `plugins/runner-scripted/fixtures/claude-code/` to `plugins/runner-claude-code/fixtures/claude-code/`,
and `tools/capture_claude.py` with it (owner, 2026-10-24). The secret-scan and provenance tests move too. These read
the new path:
- core's `test_claude_fixtures.py` (the scripted replay);
- `test_scripted_schemas.py`;
- the scripted README.

The capture tool's fake API gains a status to answer with. The new fixtures:
- `server-retries`: 529, with `CLAUDE_CODE_MAX_RETRIES=2`;
- `rate-limit-retries`: 429, with `retry-after: 0`;
- `network-retries`: `ANTHROPIC_BASE_URL` pointed at a port nobody listens on.

All three use an invalid key and no credential, so they can be captured in an agent session. Their events are written
by hand from the native lines and reviewed against D5's table, never generated. `scripts/check-paths.toml` gets a
`runner_claude_code` scope covering the plugin, with the core and scripted tests that read its fixtures.

## Risks / Trade-offs

- **Claude Code's stream-json changes without notice.** → Unknown types become `debug` logs and never fail a run.
  The fixtures record the version, and the capture tool re-captures offline in minutes. The live test is the owner's
  check against the installed version.
- **The permission-mode enum and flags are pinned to Claude Code 2.1.302.** → A new mode is refused until the schema
  adds it, and the error names the valid modes. A removed flag fails `run/start` visibly, in the live test first.
- **The person's login may need a variable not in D8's list** (a keychain or credential-helper setting on some
  platform). → The live test, run with an existing login on the owner's macOS machine, is the check. A missing
  variable shows as an authentication retry, which fails fast with `run.authentication`. Adding a name is a
  one-line change to the table.
- **SIGTERM-then-kill on POSIX, and a hard terminate on Windows, can leave a half-written file** in the workspace. →
  That's the cost of cancelling. The worktree stage keeps the theatre clean until `accept`.
- **`--setting-sources ""` behaviour for `CLAUDE.md` isn't documented.** → The live test reports it, and the README
  states what's known. It isn't asserted, because it isn't troupe's to guarantee.
- **A `.cmd` shim on Windows runs through `cmd.exe`.** → D3 keeps free text off the command line, and the stand-in
  `claude.cmd` in CI exercises that path.
- **Duplicated JSON-RPC framing between the two plugins.** → Accepted for self-containment. The conformance suite
  checks both against one contract.

## Migration Plan

None. A new runner name, a new optional table field, moved test fixtures. Actors using `scripted` are unaffected, and
rollback is reverting the change.

## Open Questions

- Does `CLAUDE.md` load under `--setting-sources ""`? The live test reports it (D4). The answer changes the README,
  not the design.
- Should policy limit which permission modes, or how large a budget, an actor may set? That belongs with policy work.
  The runner already passes only what config sets.
