# Proposal

## Why

0.2.0 changed a lot under the docs: runners, runtimes, install extras, failure handling, setup and the merge gates
all moved, and the LM Studio runner was removed. Each change updated its own pages, but nothing has checked the docs
as a whole since 0.1.0. Before the 0.2.0 release (#263), a reader should be able to install troupe, set up each
runner and runtime, and run an actor on each engine by following the docs alone (#425).

## What Changes

- **A "run an actor on it" path for every runner.** `docs/opening-night/first-performance.md` already has paths for
  Claude Code, scripted, Ollama and OpenAI. It gains one for the `anthropic` runner (Claude's API) and one for the
  `mistralrs` runner (in-process, a GGUF model), and the docs check runs each against a stand-in for its service or
  engine, as it does the others. The docs check also fails when a runner troupe has has no path, and when any page
  offers a runner troupe doesn't have (`--runner x`, `runner=x`).
- **User docs corrected against main's code:** stale runner lists (`cli.md`, `first-theatre.md`), "bundled" wording
  that predates the extras (#333), the `runtimes/` directory in the `.troupe/` trees, what a run records (runtime,
  served model, usage, cost) without claiming `status` or `logs` show cost, runtime-fit and runner-not-installed
  refusals, the audition's warm-up notices, wrong issue links (#8 for #71, closed #60 and #51 listed as planned),
  the broken `docs/cli/README.md` link, the in-process `mistralrs` runtime having no endpoint, glossary rows for
  runner, runtime and engine.
- **Precedence stated per setting, as the code has it.** Runner settings an actor sends with each run beat the
  environment, which beats the default (for example `onContextFull` over `DISABLE_AUTO_COMPACT`). The run's model
  follows the same order (actor's `model`, then `TROUPE_RUNTIME_<NAME>_MODEL`, then the runtime's model) once #451
  makes the code do so; that passage lands in its own commit, and this change merges after #451.
- **Runner READMEs:** replace the hand-written `.troupe/actors/lead.yaml` setups troupe never reads with
  `troupe init --audition --runner <x>` or the `troupe config set` lines that work; give the Claude Code compaction
  opt-in its command; fix the LM Studio-through-`anthropic` actor line (it needs `runner` and `expect`); say Ollama
  behind `anthropic` needs a runtime of the reader's own; name troupe's own refusal (`runtime.unfit`) before the
  runner's.
- **`bring-your-own-agent.md`:** the minimal SDK ships (#240); what's still to come is #58's full SDK; third-party
  runners wait on #38 and #67, not #60.
- **contributing/:** a new `contributing/quality-gates.md` saying what the merge gates on troupe expect of a
  contributor (complexity, per-package branch coverage against `quality-gates.toml`, the dependency audit, the
  per-PR mutation report and the weekly mutation run), linked from `CLAUDE.md`, `runners.md` and `releasing.md`;
  adding a runner or package includes its `quality-gates.toml` entry; `runners.md` says how a runner is wired into
  core's runner table today and that `options.schema.json` is now checked; `config.md` gains runtime `prices`,
  the model order and the `runtime.unfit` reasons; `runs.md` gains the newer notices; the SDK README lists every
  module it holds, including `process.exit_now`.
- **The actor schema's `$schema` description** says what the code writes (troupe.run's absolute URL), regenerating
  the config schema page.
- **LM Studio:** no page offers the removed runner, its built-in runtime or `troupe-run[lm-studio]`. LM Studio stays
  as an engine reached through the `anthropic` runner.
- **Issues, not vague wording**, for what the docs can't truthfully say yet, and a website issue (sidebar order for
  the Runtimes page) in 0.2.0.

## Capabilities

### New Capabilities

### Modified Capabilities
- `user-docs`: the first run gives a path for every runner troupe has, each run as written against a stand-in, and
  no page offers a runner troupe doesn't have.

## Impact

- `docs/**`, `README.md`, `plugins/*/README.md`, `packages/troupe-plugin-sdk/README.md`, `contributing/**`,
  `CLAUDE.md`.
- `protocol/schemas/config/actor.schema.json` (a description only) and the regenerated config schema page.
- `packages/troupe/tests/test_user_docs_pages.py` (the new walkthroughs and the runner checks), using the existing
  Messages API stand-in and the mistralrs engine stand-in.
- No runtime behaviour changes. Depends on #451 for the model order passage.
