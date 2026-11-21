# Tasks

## 1. The summary carries usage and cost (D1, D2)

- [ ] 1.1 Tests first, in `packages/troupe/tests/test_client_messages.py` and the projection's tests: a summary with
  `usage` and `cost` `reported` / `estimated` validates against `client/run.schema.json` and reads back; `cost` with
  another `kind`, or without `usd` or `kind`, fails both, naming `cost`; folding a run whose result carried all four
  counters and `costUsd`, one with `estimatedCostUsd`, one with neither, one with only input and output, and a run
  with no result yet gives the client-protocol spec's summaries. Verify: they fail before the change
  (`uv run pytest packages/troupe/tests/test_client_messages.py -k "usage or cost"`).
- [ ] 1.2 Add `usage` (a `$ref` to the result event's `usage`) and `cost` to the summary in
  `protocol/client/run.schema.json`, and to `RunSummary` (`core/client/messages.py`, reusing the protocol's `Usage`
  type). Verify: the schema tests from 1.1 pass, and `scripts/check.py`'s schema and protocol checks pass.
- [ ] 1.3 Read the result's usage and cost in the fold (`core/runs/projections.py`) and put them in the summary.
  Verify: the fold tests from 1.1 pass.

## 2. status and logs show them (D3, D4)

- [ ] 2.1 Tests first, in `packages/troupe/tests/test_cli_render.py`: every cli-spec scenario, with the design's
  approved lines as the expected text (reported, estimated, neither, tokens without a price, a missing counter, the
  list with notices and a cost, the logs result line in each case and the footer without them, `under $0.0001`,
  `$0`, and 0.123456 → `$0.1235`). Verify: they fail before the change.
- [ ] 2.2 Implement the `tokens:` and `cost:` lines, the list line's cost and the result line's brackets in
  `cli/render.py`, from one table of counter names and one cost formatter. Verify: the tests from 2.1 pass.
- [ ] 2.3 End to end in `packages/troupe/tests/test_cli_runs.py`: a scripted run whose result carries `usage` and
  `costUsd`, and one with `estimatedCostUsd` under a configured price, through `troupe status <run>`, `troupe status`,
  `troupe logs <run>` and `--json` (the summary has `usage` and `cost`). Verify: they pass.
- [ ] 2.4 Docs: `docs/the-company/performances-and-runs.md` says what `status` and `logs` show of usage and cost,
  drops the "don't show usage or cost yet" sentence and its #456 link, and shows the estimated line;
  `docs/prompt-book/cli.md` describes the `tokens:` and `cost:` lines outside its generated blocks. Verify: the docs
  checks in `uv run scripts/check.py` pass (links, generated blocks unchanged, CLI examples).

## 3. Integration

- [ ] 3.1 Run the full check (`uv run scripts/check.py`, after asking the owner for the slot) and keep its log in the
  scratchpad. Verify: it passes, and `openspec validate run-usage-display --strict` passes.

## Workflow follow-up

- Draft PR closing #456, act on Claude's review, mark ready once clean.
- Archive the change on the branch before the owner merges.
- After the merge, check #456 is closed and its card says Done.
