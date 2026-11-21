# Proposal: show a run's usage and cost in status and logs

Issue: [troupe#456](https://github.com/troupe-run/troupe/issues/456).

## Why

Since 0.2.0 a run records the tokens it used, cache reads and writes among them
([#293](https://github.com/troupe-run/troupe/issues/293)), and its cost, as the service reported it or estimated from
the runtime's `prices` ([#292](https://github.com/troupe-run/troupe/issues/292)). Neither `troupe status` nor
`troupe logs` shows them. `troupe logs <run> --json` is the only way to read them, so a person watching what their
runs cost has to read JSON. The runs page says so ("don't show usage or cost yet").

## What Changes

- **The run summary carries the run's usage and cost.** The client protocol's run summary gains `usage`, exactly as
  the run's recorded `result` event carries it, and `cost`: `{usd, kind}`, where `kind` is `reported` (the result's
  `costUsd`) or `estimated` (its `estimatedCostUsd`), so a reader can't take the amount without its kind. Each is
  left out when the result didn't carry it, and both before a result is recorded.
- **`troupe status <run>`** shows a `tokens:` line with each counter the runner reported, and a `cost:` line that says
  whether the service reported the cost or troupe's price estimated it.
- **`troupe status`** (the list) adds a run's cost to its line, an estimate marked as one.
- **`troupe logs <run>`** shows the tokens and cost on the result event's line, an estimate marked as one, so
  `--follow` and `perform`'s event lines show them as the result arrives.
- **Nothing is shown in place of a figure the runner didn't report.** A run with no usage has no `tokens:` line, a run
  with no cost has no `cost:` line, and a counter left out is left out of the line. Never a zero for a missing figure.
- **The docs** (the runs page and the CLI reference) say what each command shows, and the runs page loses its "not
  yet". No docs requirement changes, so `user-docs` has no delta.

Nothing recorded changes: no event, field or runner behaviour. Not **BREAKING**: the summary's new fields are
optional. Released as a protocol change (the client protocol's run schema gains fields: a `feat` commit).

Out of scope: totals across runs or an actor; budgets in money; the `context` event's token counts, which keep their
current form; which price an estimate used (the run's record has it; the line says it was estimated).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `client-protocol`: a run summary carries its result's usage, and its reported or estimated cost.
- `cli`: `status`, the list of runs and `logs` show a run's tokens and cost, saying which kind a cost is, and show
  nothing for a figure the run didn't report.

## Impact

- `packages/troupe/src/troupe/protocol/client/run.schema.json`: the summary's new fields (copied from the result
  event's definitions, so the two can't drift).
- `packages/troupe/src/troupe/core/client/messages.py` (`RunSummary`), `core/runs/projections.py` (the fold reads the
  result event).
- `packages/troupe/src/troupe/cli/render.py`: the new lines and the result line's suffix.
- `docs/the-company/performances-and-runs.md`, `docs/prompt-book/cli.md`.
- Tests: the projection, the schema, the renderers, and the CLI end to end with the scripted runner (which can
  script `usage`, `costUsd` and `estimatedCostUsd`).
