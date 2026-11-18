# Tasks

The audit findings these tasks act on are in the PR description. Each task's verification is the docs check
(`uv run scripts/check.py`, whose docs tests are `packages/troupe/tests/test_user_docs_*.py`) unless it says otherwise.

## 1. A path for every runner (spec: user-docs)

- [ ] 1.1 Write the failing checks first: every runner in core's runner table has a section on the first-run page, and
  no page under `docs/` names a runner (`--runner x`, `runner=x`) that troupe doesn't have; confirm the first fails on
  main (no anthropic or mistralrs section) and the second passes on main.
- [ ] 1.2 Add "Try it on Claude's API" (`anthropic`) to `docs/opening-night/first-performance.md`, with a test that
  runs its commands as written against the Messages API stand-in and sees `run <id> succeeded`.
- [ ] 1.3 Add "Try it in-process with mistral.rs" (`mistralrs`), with the extra, `--managed-python` on macOS, the GGUF
  model variable and the warm-up, and a test that runs it as written through the engine stand-in (design D2).
- [ ] 1.4 Point each runner README's setup at its section, replacing the hand-written `.troupe/actors/lead.yaml`
  setups; check each README's `troupe config set` lines are accepted by running them in a scratch theatre.

## 2. User docs against main

- [ ] 2.1 `README.md`, `docs/opening-night/*`: extras rather than "bundled", the six runners for `--audition`, the
  `runner.not-installed` refusal and warm-up notices, the `runtimes/` directory in the `.troupe/` tree, the broken
  `docs/cli/README.md` link, #60's stale promise.
- [ ] 2.2 `docs/prompt-book/*`: `cli.md`'s runner list and small fixes (init with `--audition` records a config
  change, discard's pushes, `--json` on `config get`/`set`), glossary rows for runner, runtime and engine and the
  `system` kind's tense, `events.md`'s "today troupe records runs".
- [ ] 2.3 `docs/the-company/*`: what a run records (runtime, served model, usage, cost; not shown by `status` or
  `logs`), runtime-fit and runner-not-installed refusals, compaction for all four tool-loop runners, worktrees built
  (#51), issue links (#8 → #71, #2, #60), `RUN_SCRATCH_ROOT` not settable, `mistralrs` taking no endpoint.
- [ ] 2.4 `docs/stagecraft/*`: the minimal SDK ships (#240), #38/#67 for third-party runners, the conformance check's
  limit, the LM Studio actor line, Anthropic reports no cost, `sh` fences, a killed perform's `interrupted`.
- [ ] 2.5 The actor schema's `$schema` description says troupe writes troupe.run's absolute URL; regenerate the config
  schema page (`uv run scripts/docs_reference.py`).
- [ ] 2.6 Runner settings' precedence (an actor's setting sent with each run, then the environment, then the default)
  in `docs/stagecraft/runtimes.md` and the Claude Code README; `DISABLE_AUTO_COMPACT` doesn't reach a performed run;
  the compaction opt-in's `troupe config set` command.
- [ ] 2.7 The model order (actor, environment, runtime) after #451, in its own commit (design D4): `runtimes.md`,
  `contributing/config.md`, the mistralrs README; verify against #451's merged code.
- [ ] 2.8 `grep -riE "lm.?studio"` across the repo outside `openspec/changes/archive`: only LM Studio as an engine
  through `anthropic` remains.

## 3. contributing/

- [ ] 3.1 New `contributing/quality-gates.md`: complexity, coverage against `quality-gates.toml` (floor, tolerance,
  raising a baseline, a new package's entry), the dependency audit, the per-PR mutation report and the weekly run, each
  checked against `scripts/quality_gates.py`, the workflows and infrastructure's docs; link it from `CLAUDE.md`,
  `runners.md` and `releasing.md`.
- [ ] 3.2 `runners.md`: wiring a runner into core's runner table (#38 open), `options.schema.json` now checked,
  `quality-gates.toml` in adding a runner, conformance's character check, `notRetried` across runners.
- [ ] 3.3 `config.md` (runtime `prices`, `runtime.unfit` reasons, in-process runtimes), `runs.md` (newer notices,
  runtime resolution among the refusals), the SDK README (every module, `process.exit_now`).

## 4. What the docs can't say, and the other repositories

- [ ] 4.1 Open issues (on the board, after checking for duplicates) for what the docs can't truthfully say yet
  (design D6); link each from the page where it matters.
- [ ] 4.2 Open the website issue (sidebar order, 0.2.0) and the infrastructure issues (milestone description, org
  profile), each on the board.

## 5. Verification

- [ ] 5.1 Run each path for real where this machine can (scripted, Ollama, mistral.rs, LM Studio through `anthropic`
  if a model is loaded), one at a time with load under ~40; record which ran for real and which against stand-ins and
  fixtures in the PR.
- [ ] 5.2 `uv run scripts/check.py` passes.

## Workflow follow-up

- Merge after #451 (design D4); `/openspec-archive-change` before merging.
- After the merge, comment on #425 with the PR and the archived change.
