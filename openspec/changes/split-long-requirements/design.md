# Design

## Context

See proposal.md, Why. Two requirements break strict validation: `runner-protocol`'s "Run start carries everything the
runner may use" and `scripted-runner`'s "A script is a list of steps played in order". OpenSpec's guidance for
splitting one is fixed. Under MODIFIED, keep the header and every scenario, and cut the description to one behaviour
without changing its meaning. Under ADDED, give each behaviour removed from it its own requirement, with its own
scenarios.

Tests point at requirements with a `# Requirement: <header>` comment above the tests that cover it. Three sections
name these two requirements, and two of them add a sub-behaviour in brackets:

- `packages/troupe/tests/test_runner_schemas.py:285` and `:372` ("(options are an extension point)")
- `packages/troupe/tests/test_run_host.py:615`
- `plugins/runner-scripted/tests/test_scripted_runner.py:104` and `:380` ("(when troupe's messages are read)")

## Goals / Non-Goals

**Goals:**

- Every sentence of the two descriptions survives word for word, either in the original or as an added
  requirement's description. Only the sentence boundaries move.
- Every added requirement has a scenario with a test that fails when its behaviour breaks.

**Non-Goals:**

- Rewording any other requirement, or fixing any other spec's warnings. There are none under `--strict` today.
- Changing behaviour. If a new test fails on main, the requirement it covers already isn't met. That's a bug for its
  own issue, not something to fix here (D4).
- A gate that runs strict validation (Open Questions).

## Decisions

### D1: Split at sentence boundaries, keeping the text word for word

Each removed sentence becomes the added requirement's description almost unchanged. Two need a small edit to stand
alone:

- "The runner SHALL use no other source of direction, character or configuration from troupe" gains "than the
  `run/start` request". The original sentence had that meaning from its place right after the list of what
  `run/start` carries.
- "The contract's schema SHALL mark the options as …" becomes "the `run/start` options", for the same reason.

Rewording to tighten the text was the alternative. It was rejected because the issue asks for no change of meaning,
and word-for-word text is the easiest way to show that in review: the diff of each description is a cut.

### D2: The original keeps every scenario, even ones that now read closer to an added requirement

The options scenarios ("opaque to the host", "checked against the runner's schema", "refuses options it doesn't
understand") and the two message-timing scenarios would fit the added requirements better. OpenSpec's guidance says to
keep every scenario under MODIFIED, so they stay. Each still checks something the original's description states: the
options are an object that `run/start` carries, and the steps play in order. The added requirements get scenarios for
the behaviours no scenario named. Each such scenario already has a test, or gets one (D4).

Moving the scenarios was the alternative. It was rejected because it goes against the guidance the split follows,
and because a later change can still move them deliberately.

### D3: "The steps SHALL cover" stays a floor, not a closed list

The published options schema defines ten step kinds. The sentence lists eight. `replay` belongs to "Recorded streams
replay verbatim", and `checkCharacter` to "A script can check the character it received". "Cover" means at least
these, so the added requirement's scenario checks that each listed kind is defined, not that no others are. Changing
it to a closed list would change its meaning, which this change mustn't do.

### D4: New tests are written first and must pass on main

Each added requirement's scenario is behaviour the code already claims. Its test is written and run against the code
on main before any spec moves, following the rule that a non-goal ("no behaviour changes") must be something a test
can falsify.

- **No other source**: run a scripted actor with a character, a direction and an option whose value is a unique
  marker, through the host. Assert that neither the argv the host spawns nor the environment it passes holds any of
  them. If the host's test harness can't observe argv and environment without a production change, stop and ask
  rather than add a seam.
- **Options extension point**: `test_the_contract_alone_accepts_only_empty_options` already checks the scenario. It
  moves under the added requirement's comment.
- **Step kinds**: read `options.schema.json` and assert that each listed kind is a `required` key of one `step`
  alternative.
- **Wait and replay delays**: use the in-process harness `_played_with_everything_queued`, with `onCancel: "ignore"`
  and a `run/cancel` queued. A `wait` of a few hundred milliseconds, and a replayed recording whose delays come to the
  same, must each answer the cancel and then play on. The test asserts the answer's position among the sent
  messages, not wall time, so it can't flake on a slow machine.

If any of these fails on main, stop. Record the failure on a new issue and ask the owner whether to fix it here.

### D5: Test comments follow the requirement each test checks

A bracketed sub-behaviour comment is replaced by the header of the requirement whose scenario the test checks:

- `test_runner_schemas.py:372`: `test_the_contract_alone_accepts_only_empty_options` goes under "Run start options
  are an extension point". `test_with_a_runners_schema_bound_…` stays under "Run start carries everything the runner
  may use", whose "Options checked against the runner's schema" scenario it checks.
- `test_scripted_runner.py:380`: the two existing tests check the original's scenarios, so the comment drops its
  bracket. The two new tests go under "Steps that don't wait play without reading troupe's messages".
- The new host test goes under "The runner takes direction, character and configuration only from its run start",
  with `(spec: runner-protocol)` as its neighbour has. The step-kind test goes under "A script's steps cover what a
  runner can send or do".

## Risks / Trade-offs

- [A new timing test is flaky on Windows CI] → It uses the in-process harness with every message queued before the
  first step, and asserts message order, not elapsed time. It runs the full OS matrix before the PR merges.
- [The archive merges the MODIFIED block wrongly and drops a scenario] → After archiving, count each requirement's
  scenarios in the main spec against main's, and run `openspec validate --specs --strict`.
- [Main gains another over-long requirement before this merges] → The final task reruns the strict validation on the
  rebased branch.

## Open Questions

- **Where a strict-validation gate should run.** #155 suggests `scripts/check.py`. That conflicts with the
  `quality-check` requirement "No gate reads OpenSpec artifacts". It would also never run on the commits that matter:
  `check-paths.toml` skips the check for commits that touch only `openspec/**`. The candidates are the guard in
  `troupe-run/infrastructure`, which already runs on every push and is a required check, or a CI job in this
  repository. Either needs Node and the `openspec` CLI on the runner. The answer changes nothing in this change's
  specs or tasks. **Answered (owner, 2026-10-23): the guard.** It goes to a follow-up issue in
  `troupe-run/infrastructure`, on the roadmap board, linked from #155.
