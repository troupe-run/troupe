# Tasks

## 1. Scaffold the plugin and wire it into the workspace (design D1)

- [x] 1.1 Create `plugins/runner-claude-code/`:
  - `pyproject.toml`: `troupe-runner-claude-code`, `0.0.1.dev0`, `requires-python` as the scripted runner's, no
    dependencies, and the script `troupe-runner-claude-code`;
  - `LICENSE` (Apache-2.0, copied);
  - a stub `README.md`;
  - `src/troupe_runner_claude_code/`, holding `__init__.py` (`NAME`, `__version__`), `__main__.py`, `py.typed` and
    `defaults.py` with D11's four settings. `__main__.py` lands with `runner.py` (7.2), which it imports.

  Verify: `uv sync` succeeds and `uv run python -c "import troupe_runner_claude_code"` exits 0.
- [x] 1.2 Wire the member into the root `pyproject.toml`:
  - `[tool.uv.sources]` and the dev group;
  - ruff `src`, mypy `files` and `mypy_path`, pytest `testpaths`;
  - import-linter `root_packages`, the source modules of `plugins import nothing from troupe`, and a new contract
    that only `troupe_runner_claude_code.processes` imports `signal`, `ctypes`, `msvcrt` or `_winapi`.

  Also add the member to `release-please-config.json` and `.release-please-manifest.json` (`"0.0.0"`), and give it a
  `runner_claude_code` scope in `scripts/check-paths.toml`, whose tests are the plugin's own, core's and the
  workspace tests. Verify: `uv run pytest scripts/tests/workspace` passes, and `uv run lint-imports` passes. A
  scratch module importing `troupe` from the plugin must make it fail, and is then removed.

## 2. Move the Claude Code fixtures and correct them to the contract (design D5, D13)

- [x] 2.1 `git mv` `plugins/runner-scripted/fixtures/claude-code/` and `tools/capture_claude.py` to
  `plugins/runner-claude-code/`. Move the fixture checks from `test_scripted_fixtures.py` to
  `plugins/runner-claude-code/tests/test_fixtures.py`: the secret scan, the provenance, and the pairing. Then point
  the remaining readers at the new path: `packages/troupe/tests/test_claude_fixtures.py`, `test_scripted_schemas.py`,
  `plugins/runner-scripted/README.md`, and the capture tool's docstring. Verify: `grep -rnE
  "runner-scripted/(fixtures|tools)"` finds nothing outside `openspec/changes/archive/`. These pass: `uv run pytest
  plugins/runner-claude-code/tests/test_fixtures.py plugins/runner-scripted/tests
  packages/troupe/tests/test_claude_fixtures.py`.
- [x] 2.2 Write a failing pairing test: every hand-written `result` event's `usage` has each counter its native
  `result` record has. Run it to show `success-with-tools` and the error fixtures fail it. Then add the missing
  `cacheReadTokens` and `cacheWriteTokens` to those events, in a commit of its own that cites contributing/runners.md's
  table and 613ca5b. Verify: the new test passes, and `test_claude_fixtures.py` still derives every `expected.json`
  outcome.

## 3. Capture the three new retry fixtures offline (design D13)

- [x] 3.1 Extend `capture_claude.py`:
  - the fake API takes a status to answer with (401 as now, 429 with `retry-after: 0`, or 529);
  - a mode points `ANTHROPIC_BASE_URL` at a port nobody listens on;
  - three fixtures: `server-retries`, `rate-limit-retries` and `network-retries`, each with
    `CLAUDE_CODE_MAX_RETRIES=2`.

  Verify: running the tool for each writes `recording.jsonl` and `provenance.json`, the provenance says no credential
  was used, and the secret scan passes.
- [x] 3.2 Hand-write each new fixture's events and `expected.json` from its native lines, using D5's retry-reason
  rules. Record in each provenance that the events are hand-written and reviewed. Extend
  `test_there_are_fixtures_for_each_failure_shape` to name the three. Verify: `test_fixtures.py` passes, and
  `test_claude_fixtures.py` replays each through the scripted runner to the outcome its `expected.json` states.

## 4. Options and published schemas (design D10)

- [ ] 4.1 Add `schemas/options.schema.json` and `schemas/errors.schema.json`, closed, with D10's rules and the four
  error codes, and `$id`s under `https://troupe.run/plugins/runner-claude-code/`. Verify: a schema test, copied from
  `test_scripted_schemas.py`'s pattern, loads both with the contract's schemas and checks each is draft 2020-12 and
  closed.
- [ ] 4.2 Add `options.py`: `parse_options(value) -> Options`, raising `OptionsError(code, where, problem, fix)`
  for an unknown option (`claude-code.unknown-option`) or a malformed value (`claude-code.invalid-options`). Verify
  with `test_options.py`:
  - one test per rule in D10, for both an accepted and a refused value. A refused value names `where`, and its fix
    names what's valid;
  - a hypothesis test that generates option objects, from both near-valid and arbitrary JSON, and asserts that
    `parse_options` and the published schema accept and refuse exactly the same ones.
- [ ] 4.3 Document the options, their rules and the default budget in the plugin README. Verify: a README test (as
  `test_runners_doc.py` does for the contract) checks that every option in the schema has a row, and every row an
  option.

## 5. The mapper (design D5)

- [ ] 5.1 Add `mapping.py` with `Mapper(runner_version, event_max_bytes)` and `feed(line: bytes) -> list[Out]`,
  following D5's table, its strict JSON parsing and its summaries. Verify with `test_mapping.py`:
  - for every fixture, feeding its native lines yields exactly the recording's transcript records and events, in
    order;
  - one named test per row of D5's table and per scenario of the spec's mapping requirements, including the
    synthetic `init`, an unknown `tool_use_id`, the permission-denial log, a budget stop, an unreadable `result`, an
    unknown type noted once, a non-JSON line, and a non-UTF-8 line sent as `base64`;
  - a summary cut to a 1 MiB tool output, on a UTF-8 boundary, with the bytes-left-out suffix and the true
    `outputBytes`.
- [ ] 5.2 Add a hypothesis property test, fed by random bytes, random JSON objects and mutated fixture records. It
  asserts that `feed` never raises, and that every event, once numbered:
  - validates against `run-event.schema.json`;
  - fits `event_max_bytes`;
  - if it's a `tool_result`, follows its `tool_call`;
  - doesn't follow a `result`.

  Verify: the test passes at the `ci` hypothesis profile. A deliberately broken mapper (a scratch edit, reverted)
  makes it fail.
- [ ] 5.3 Update contributing/runners.md's "Mapping an engine: Claude Code" table for what D5 adds:
  - `network` is a retry with no HTTP status;
  - permission denials;
  - records the mapping doesn't name;
  - non-JSON lines;
  - summaries cut below `eventMaxBytes`;
  - "the Claude Code runner implements this" now links to the plugin.

  Verify: `uv run pytest packages/troupe/tests/test_runners_doc.py` passes, with any table assertions it makes
  updated to match.

## 6. Claude Code's command line and the OS seam (design D3, D4, D6, D9)

- [ ] 6.1 Add `command.py`: from `Options`, the character, the direction and a fresh private directory, build the
  argv, the stdin bytes, the character file and the settings file, as D3 and D4 describe. Verify with
  `test_command.py`:
  - the fixed flags;
  - `--setting-sources ""` by default, and the joined subset when it's set;
  - `--max-budget-usd 5` by default;
  - no `--permission-mode` unless it's set;
  - the character and settings files, holding exactly the character's UTF-8 and the allow and deny rules;
  - a direction with quotes and newlines appears in stdin and in no argv element;
  - the private directory is outside the workspace and is 0700 on POSIX.
- [ ] 6.2 Add `processes.py`, the only module using `signal` or `os.name`. It holds:
  - `find_claude(path)`, which uses `shutil.which`;
  - `start(argv, cwd, env)`, which keeps the child in the runner's process group;
  - `stop(proc, grace) -> int`: SIGTERM then SIGKILL on POSIX, and terminate on Windows;
  - `exit_code(returncode) -> int`, D7's mapping.

  Verify with `test_processes.py` on all three operating systems, using a Python child as the process:
  - `stop` ends a child that ignores nothing, and a POSIX child that ignores SIGTERM, within the grace plus a margin.
    Afterwards the pid is gone;
  - `find_claude` finds a `claude.cmd` on Windows and an executable `claude` on POSIX;
  - `exit_code` maps 0, 1, 143, -15, and a Windows code above 255.

  The import-linter seam contract from 1.2 passes.

## 7. The runner process (design D2, D6, D7)

- [ ] 7.1 Add `tests/fake_claude.py`, the stand-in `claude`, and a fixture that puts it first on a temporary `PATH`:
  an executable shim on POSIX and `claude.cmd` on Windows. The stand-in:
  - records its argv, stdin bytes, cwd and environment as JSON to `FAKE_CLAUDE_RECORD`;
  - replays `FAKE_CLAUDE_FIXTURE`'s native lines;
  - exits with `FAKE_CLAUDE_EXIT`;
  - hangs with `FAKE_CLAUDE_HANG`;
  - exits 143 on SIGTERM without a `result`.

  Verify: a test runs the stand-in directly with each fixture and checks it writes the fixture's native lines byte
  for byte.
- [ ] 7.2 Add `runner.py`, the JSON-RPC loop, and `tests/claude_harness.py`, which follows `scripted_harness.py` and
  validates every message against the contract with the runner's schemas bound. The loop:
  - handles the handshake;
  - checks before answering `run/start`, refusing `claude-code.not-found`, `claude-code.unknown-option`,
    `claude-code.invalid-options` and `claude-code.start-failed`;
  - starts Claude Code after answering, and streams the mapper's output, numbering events;
  - handles cancel, end of input, and `shutdown` after the result, with D7's exit codes and stderr lines;
  - removes the private directory on every path.

  Verify with `test_runner.py`:
  - every spec scenario for the handshake, the command line, stdin, the character, the isolation, the options and the
    refusals;
  - Claude Code exiting before its init (a synthetic `init`, a `log` error, no `result`, a non-zero exit);
  - an ok result then exit 1 (the runner exits non-zero);
  - the stand-in's stderr reaching the runner's stderr;
  - cancel mid-run and end of input mid-run, after each of which the stand-in's recorded pid is gone before the
    runner exits, and no event follows the cancel;
  - the private directory gone after each of those paths.
- [ ] 7.3 Complete the plugin README: what the runner does, how it finds `claude`, the command line it builds, the
  isolation and `settingSources`, cancelling, the exit codes, the limits (D11), the schemas, and the fixtures and how
  to capture them. Add the plugin to `plugins/README.md`'s table. Verify: the README test from 4.3 passes, and every
  path the README links to exists (checked by the same test).

## 8. Perform runs the Claude Code runner (spec: runs; design D8)

- [ ] 8.1 Before changing perform, write a test that passes on main and must keep passing: a `scripted` actor's
  runner gets only the platform minimum, even when `PATH` and a secret are set in perform's environment. Then give
  `interim.Runner` its `environment` field (`()` for `scripted`), and add the `claude-code` entry with D8's names.
  `perform` copies each name that's set into `RunnerCommand.env`. Verify with `test_interim.py` and `test_perform.py`:
  - the scripted test still passes;
  - `claude-code` resolves, and passes the conformance checks with the stand-in on `PATH`;
  - an unknown runner is refused, naming both runners;
  - each scenario of "Perform passes a runner only the variables it is known to need", using the stand-in's recorded
    environment.
- [ ] 8.2 `troupe config set actors.x.runner=claude-code` with a valid options file is accepted, and an option the
  runner doesn't define is refused naming the runner's options schema. Verify with a test in `test_config_changes.py`
  or its neighbour, beside the scripted runner's cases.
- [ ] 8.3 Update the user docs. In `docs/stagecraft/bring-your-own-agent.md`, "Runners today" names the Claude Code
  runner, and says it uses the person's login and leaves out their settings by default. In
  `docs/opening-night/first-performance.md`, "Choose a runner" shows a `claude-code` actor with `permissionMode:
  acceptEdits` and `allowedTools`, and says why it needs them. Update the runner list in contributing/runners.md.
  Verify: `uv run pytest packages/troupe/tests -k docs` passes, and the docs' commands, run against a scratch theatre
  with the stand-in on `PATH`, behave as written.

## 9. Through the host, end to end (spec: claude-code-runner, actor-runners)

- [ ] 9.1 Add `packages/troupe/tests/test_claude_code_runner.py`. For each fixture, the stand-in plays it through
  `run_actor`, with fail-fast on and with it off (`RunLimits`). Each run must give the outcome and error code in
  `expected.json` and its `withoutFailFast`, and every message must validate against the contract with the runner's
  schemas bound. It also checks:
  - a cancel mid-run ends `cancelled` within `RUNNER_CANCEL_GRACE_SECONDS`;
  - an ok result followed by exit 1 ends `failed` with `run.unclean-exit`;
  - the transcript the host stores is the fixture's native lines byte for byte.

  Verify: the file passes locally.
- [ ] 9.2 Add the Claude Code runner, with the stand-in on `PATH`, to `test_runner_conformance.py`. Verify: every
  check passes.
- [ ] 9.3 Add `test_perform_claude_code.py`: `troupe perform` on a theatre with a `claude-code` actor, the
  `success-with-tools` stand-in, and `AWS_SECRET_ACCESS_KEY` set. Verify:
  - the run ends `succeeded`;
  - its recorded start names runner `claude-code` and engine `claude-code` `2.1.296`;
  - the stand-in's recorded environment has `PATH` but not the secret.

## 10. The opt-in live test (spec: "A live test runs real Claude Code only when asked"; design D12)

- [ ] 10.1 Add `packages/troupe/tests/test_claude_code_live.py`, skipped unless `TROUPE_LIVE_CLAUDE_CODE=1`, with a
  reason naming the variable and the credentials it can use. It is D12's run: a pinned model, `maxBudgetUsd` 0.10, the
  capture tool's prompt, `allowedTools` `Write` and `Read`, and no `permissionMode`. It prints which credential it used
  and whether `CLAUDE.md` loaded. Verify: without the variable, `uv run pytest
  packages/troupe/tests/test_claude_code_live.py -rs` reports it skipped with that reason, and CI's logs show it
  skipped on all three operating systems.
- [ ] 10.2 **Owner:** run the live test once with a credential (`CLAUDE_CODE_OAUTH_TOKEN` or `ANTHROPIC_API_KEY`) and
  once with only the existing login, on macOS. Paste the outcomes and what it printed into the PR. An agent session
  doesn't run this. Verify: both runs `succeeded`, and the README's `CLAUDE.md` sentence matches what was printed.

## 11. Integration

- [ ] 11.1 Run `uv run scripts/check.py`. Verify: it passes, which includes ruff, mypy --strict, import-linter and the
  full test suite.
- [ ] 11.2 Push the branch and open the PR (`Closes #55`). Verify: every CI job passes on Linux, macOS and Windows. Read
  the jobs' logs to confirm that the cancel and process tests ran on Windows (not skipped), and that the live test was
  skipped.

## Workflow follow-up

- Run `/opsx:archive` on the branch before merging, so the PR lands code, tests and specs together.
- After the merge, check #55 is closed and its roadmap card says Done. Then comment on #55 with the PR and the
  archived change.
