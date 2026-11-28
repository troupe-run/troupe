# Tasks

## 1. Lineage names a performance

- [x] 1.1 Add `performance` to `Lineage`, `Command` (copied by `acting_as`), `store.command`, `record_reaction` and
  `lineage_problem` (canonical lowercase UUID, left out when there's none, `null` refused). Verify: unit tests build a
  lineage with and without it and check `to_data` and `lineage_problem` against `lineage.schema.json`.
- [x] 1.2 Check the topic rule in `record_with_lineages` (D4): run and performance topics must name a performance, and
  every other topic mustn't. Both are refused with `events.lineage-invalid` naming `performance`, and nothing is
  written. Verify: tests for both refusals, plus a config change that records with no `performance`.
- [x] 1.3 Add `performance` to `lineage.schema.json`. Make the run event schemas require it and the config event
  schemas refuse it (D5). Verify: schema tests for a run event without it and a config event with it, and the
  protocol strictness check passes.
- [x] 1.4 Update `docs/the-company/lineage.md` and `docs/stagecraft/read-the-lineage.md` for `performance`. Verify:
  the docs check passes.
- [x] 1.5 Add "Records an older troupe wrote" to `contributing/releasing.md` (the owner's pre-1.0 rule,
  2026-11-28). Verify: the docs check passes.

## 2. The performance aggregate

- [x] 2.1 Add `Performance` (`troupe.core.runs.performance`) with `Started` (`performed`, `steps`, `direction`,
  `config`) and `Ended` (`outcome`), refusing a second end with `performance.out-of-sequence`. Catalogue the code.
  Verify: unit tests for each event and for the refusal.
- [x] 2.2 Add `performance-started.schema.json` and `performance-ended.schema.json`, register the topics, and add a
  required `step` to `run-started.schema.json` and `Run.Started`. Verify: recorded events validate against their
  schemas in the existing every-event check.

## 3. Perform records a performance

- [x] 3.1 `perform` mints a performance id and records `Performance.Started` in the run's start batch, with every
  person, agent and troupe command carrying the performance (D2, D4). Verify: integration tests show both starts in
  one batch, every event in both streams naming the performance, and a refused start writing neither.
- [x] 3.2 Record the performance's end with the event that settles it (D3): with the run's end when no gate follows
  (`completed`, `failed` or `cancelled`), with troupe's acceptance, and no end while a cue is open. Verify: an
  integration test for each row of D3's table that `perform` reaches, including Ctrl-C and could-not-start.
- [x] 3.3 Send `performance-started`, and add `performanceId` and `step` to `started` and `RunSummary`, in messages
  and the client schemas. Verify: perform's updates and result validate against the client schemas in the client
  protocol tests.
- [x] 3.4 Make the CLI print `troupe: performance <id> (<actor>) starting` before the run line, and
  `performance <id>: run <id> succeeded` on standard output (D7). Update `docs/opening-night/first-performance.md`
  and `docs/prompt-book/cli.md`. Verify: CLI tests of perform's standard error and standard output.

## 4. Answers and settling name the performance

- [x] 4.1 `approve` records the acceptance and the performance's end (`completed`) in one batch, and `reject` the
  rejection and the end (`rejected`). Both name the performance in their lineage. Verify: gate tests read both events
  and their lineage.
- [x] 4.2 `accept` and `discard` name the run's performance in their lineage. They record nothing in a performance that
  has ended (a failed run's), and end one its perform left open: accept → `completed`, discard → `rejected` (owner,
  2026-11-28). Verify: settling tests for a failed run's accept and discard, and
  `test_settling_a_run_whose_performance_was_left_open_ends_it_in_the_same_batch`.

## 5. Reading performances back

- [x] 5.1 `RunView` reads `performance` and `step`. Reading runs back refuses every run whose start has no
  `performance` with `run.recorded-before-performances` (D8), which lists the runs, their segment files, which files
  hold anything else, and the fix. Catalogue the code. Verify: projection tests for a run with a performance, and for
  a store holding a pre-performances run's segment alone and one sharing a segment with a config change. Each
  checks the error's details and fix.
- [x] 5.2 Extend `resolve` to performance ids and prefixes (D6). Add `performance.several-runs` and catalogue it.
  Verify:
  - `diff`, `approve` and `logs` work through a performance id;
  - a prefix that matches a run and a performance is refused as ambiguous;
  - a store with two runs naming one performance raises `performance.several-runs`.
- [x] 5.3 Make status lines start with the performance's id, have `status <run>` show `performance: <id> (step 1)`, and make the limit count performances. Verify: CLI status tests, and a limit test with three performs.
- [x] 5.4 Update `docs/the-company/performances-and-runs.md` (a performance's record, the ids, status) and the
  glossary's `performance` entry, and regenerate `docs/prompt-book/events.md`. Verify: the docs and reference checks
  pass.

## 6. Integration

- [x] 6.1 Rewrite or regenerate every test fixture that holds recorded run events without a performance. Verify: the
  full `uv run scripts/check.py` passes, with its output kept in a scratch file.
- [x] 6.2 Run `openspec validate performances --strict` and the spec size gate (`quality_gates.py size`). Verify:
  both pass.

## Workflow follow-up

- Draft PR "Part of #124", with the commit that changes the protocol marked breaking (`!`, as `feat(runs)!:`) and a
  `BREAKING CHANGE:` footer.
- Act on Claude's review, mark the PR ready, then archive.
- After the merge: troupe-run/infrastructure's pull request recording the `performances` spec's Purpose.
- Then `actor-sequences` in a fresh worktree.
