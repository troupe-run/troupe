# Design

## Context

Four read-only audits checked the docs against main's code (f4f184d4): the user docs, the runner and Stagecraft pages
with the runner READMEs, `contributing/` with `CLAUDE.md` and the SDK README, and the website. The findings drive the
tasks. The first-run page already has walkthroughs that the docs check runs against stand-ins: Claude Code (a stand-in
`claude`), scripted, Ollama (`ollama_stand_in`) and OpenAI (`openai_stand_in`). Core's tests also have a Messages API
stand-in (`anthropic_stand_in`), and the mistralrs plugin has an engine stand-in with a test-only entry point
(`plugins/runner-mistralrs/tests/stand_in_runner.py`) that the conformance suite runs.

## Goals / Non-Goals

**Goals:**
- Every instruction in `docs/`, the README, the runner READMEs and `contributing/` is what main's code does.
- Every runner has a short path to a first run, checked by the docs check, so it can't drift.
- A contributor can tell from `contributing/` what each merge gate expects of them.

**Non-Goals:**
- Changing runtime behaviour. The model order is #451's code change; this change only documents it.
- The website's own pages (an issue there) and infrastructure's milestone and org profile text (issues there).
- A full SDK, third-party runners, or showing cost in `status` and `logs`: they aren't built, and the docs say so or
  an issue tracks them.

## Decisions

**D1. The runner paths live on the first-run page, one section per runner.** That page already holds four, with
tests. The anthropic and mistralrs sections follow the OpenAI section's shape: a new repository,
`troupe init --audition --runner <name>`, commit, `troupe perform lead`. The runner READMEs link to their section
rather than repeating it, and keep only what's specific to the runner (options, engines, live tests). Alternative: a
section in each README. Rejected: READMEs aren't published on troupe.run, and the docs check reads `docs/`.

**D2. The mistralrs path runs against the engine stand-in, through the test-only entry point.** The test points the
`mistralrs` entry of core's runner table at the plugin's `stand_in_runner.py`, as the conformance test does, and
sets the page's `TROUPE_RUNTIME_MISTRALRS_MODEL` line to a file in the test's directory. Production code gets no
hook. The audition's warm-up runs through the same stand-in. The anthropic path runs as the OpenAI one does:
`TROUPE_RUNTIME_ANTHROPIC_ENDPOINT` points the built-in `anthropic` runtime at the stand-in, with a made-up key in
`ANTHROPIC_API_KEY`.

**D3. A runner the page lacks, or a page offering an unknown runner, fails by name.** The check compares the
first-run page's runner sections with core's runner table, and scans every page under `docs/` for `--runner <name>`
and `runner=<name>` against the same table. It reads the table rather than a list in the test, so a new runner
can't be missed.

**D4. Precedence is stated per setting.** Runner settings an actor sends with each run beat the environment, which
beats the default; that's true today. The owner decided (2026-11-18) that the run's model follows the same order
(the actor's `model`, then `TROUPE_RUNTIME_<NAME>_MODEL`, then the runtime's), fixed in #451. The passages that state
the model order are one commit, and the PR merges after #451 so the docs are true at each merge. If #451 slips, that
commit is changed to the current order instead.

**D5. The merge gates get their own contributor page.** `contributing/quality-gates.md` covers each gate: where it
runs, what failing looks like (the messages from `scripts/quality_gates.py`), what to do (raise a baseline by hand,
add a package's entry, update a dependency), and the mutation report. The weekly mutation run on troupe is described
only as far as it has run; what it can't say yet is an issue (D6). `CLAUDE.md`, `runners.md` and `releasing.md` link
to it rather than repeating it.

**D6. What the docs can't say truthfully becomes an issue.** Candidates from the audits, each checked for an existing
issue first: the scripted runner's misleading `init`-step error; the conformance check can't take a runtime;
`status` and `logs` show no usage or cost; mutation testing doesn't reach `plugins/` or `scripts/`; the website's
sidebar order (website, 0.2.0); the 0.2.0 milestone's description and the org profile's status line
(infrastructure).

**D7. Each path is also tried for real where this machine can.** The scripted, Ollama and mistral.rs paths run
locally (Ollama is installed; mistral.rs with a small GGUF), and LM Studio through `anthropic` if a model is loaded.
Claude Code, OpenAI and Claude's API need accounts, so they're checked against the stand-ins and recorded fixtures
only. The PR says which was which. One heavy run at a time, with the load under ~40.

## Risks / Trade-offs

- [The extras install from a release tag works only from `troupe-run-v0.2.0`] → the install page names the tag form,
  which is true once #263 tags it; `/docs/` on troupe.run shows the tagged docs, `/docs/next/` main's.
- [Merging after #451 ties this PR to it] → D4's fallback.
- [The mistralrs test depends on the plugin's test stand-in by path] → the conformance test already does, and the
  check-paths reach covers it.
