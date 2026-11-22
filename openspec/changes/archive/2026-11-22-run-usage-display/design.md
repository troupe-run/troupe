# Design: show a run's usage and cost in status and logs

## Context

A run's `result` event (runner contract, `run-event.schema.json#/$defs/result`) carries `usage` (`inputTokens`,
`outputTokens`, `cacheReadTokens`, `cacheWriteTokens`, each optional) and either `costUsd` or `estimatedCostUsd`, never
both. troupe records it as a `Run.Reported` event, after the host has dropped any estimate it gave no price for. The
runs projection (`core/runs/projections.py`) folds a run's events into its summary, which `status` returns and `logs`
returns beside the log. `cli/render.py` turns both into text. Today the fold counts the result event and keeps it in
the log, and nothing reads its usage or cost.

## Goals / Non-Goals

**Goals:** show what the owner approved on 2026-11-21 (the examples below), from what's already recorded.

**Non-Goals:** no change to any recorded event, the runner contract or a runner; no totals; no change to how the
`context` event's token counts are shown.

## The approved look (owner decision, 2026-11-21)

These are the cli spec's scenarios.

**Reported cost** (Claude Code):

```
$ troupe status <run>
  ...
  outcome: succeeded
  events: 42
  tokens: 1,204 input, 9,817 output, 182,330 cache read, 14,022 cache write
  cost: $0.4213, reported by the service
  ended: 2026-11-21T09:16:40Z

$ troupe status
0193a4c2-…  succeeded            tester           2026-11-21T09:14:02Z  42 events, $0.4213

$ troupe logs <run>
    41 2026-11-21T09:16:39Z result: ok: All 18 tests pass. (tokens 1,204 in, 9,817 out, 182,330 cache read, 14,022 cache write; cost $0.4213, reported)
run 0193a4c2-…: succeeded
```

**Estimated cost** (OpenAI with a price in `runtimes.openai.prices`):

```
  tokens: 3,410 input, 2,066 output, 21,504 cache read, 0 cache write
  cost: ~$0.0136, estimated from the runtime's price

0193a4d0-…  succeeded            reviewer         2026-11-21T09:20:11Z  17 events, ~$0.0136 estimated

    16 2026-11-21T09:20:58Z result: ok: Reviewed 3 files. (tokens 3,410 in, 2,066 out, 21,504 cache read, 0 cache write; cost ~$0.0136, estimated)
```

**Neither** (Ollama): no `tokens:` or `cost:` line, the list line ends at `17 events`, and the result line is as
today. Tokens without a price show the tokens only. A counter the runner didn't report is left out; one reported as
0 shows 0.

## Decisions

### D1. The summary carries `usage` and `cost: {usd, kind}`

`usage` is the result's object as recorded; its schema is a `$ref` to the result event's `usage`, so the two can't
drift. `cost` is `{usd, kind}` with `kind` `reported` or `estimated` (owner decision). One object, rather than
mirroring `costUsd` and `estimatedCostUsd`, means a client reading the amount has the kind in hand: the renderer
branches on one field, and a future kind (a cost troupe works out itself, say) is a new enum value, not a third
field. The runner contract keeps its two fields: there the point was that an old reader of `costUsd` never sees an
estimate, which a new summary field doesn't have to guard against.

Alternative: mirror the contract's two fields. Rejected by the owner's decision, and for the reason above.

### D2. The fold reads the result as it's recorded

The fold's `Run.Reported` branch already sees every event. When the event is a `result`, it keeps its `usage` and
cost. A run has at most one result (the contract), so there's no merging. Usage and cost come from the reported
event, not the run's end, so they appear once the result is recorded, even before the end; they're not among the
fields "a summary that hasn't ended carries nothing from the run's end" refuses. A result recorded as `oversized`
has nothing readable, so the summary has neither, which is what the run then shows: no figure, never a guess.

### D3. Rendering lives in `render.py`, from the summary and the event

`status <run>` and the list render from the summary (`cost`, `usage`). The logs result line renders from the event
itself (`costUsd` / `estimatedCostUsd`, `usage`), since `render_event` has only the event, and that's also what
`perform`'s event lines and `logs --follow` print as the result arrives. One helper formats a cost from an amount and
a kind, and one formats the counters; both forms of a line (`input` / `in`) come from one table of counter names, so
`status` and `logs` can't name a counter differently.

### D4. Formatting

Four decimal places with half-up rounding of the displayed value (`Decimal`, not `round`, so 0.00005 isn't banker's
rounded to 0.0000); a non-zero amount that would show `$0.0000` shows `under $0.0001`; exactly 0 shows `$0`.
An estimate is `~` before the amount everywhere, and the word `estimated` after it. Token counts use `{:,}`.

## Risks / Trade-offs

- [The result line gets long with four counters] → It's the line that carries them; the terminal wraps it. The
  status list stays short (cost only).
- [`--json` consumers see two new optional summary fields] → Additive; the client protocol takes new optional
  fields, released as a `feat`.
- [A host that dropped an unrequested estimate] → The recorded result has no estimate, so nothing is shown; the
  `run.estimate-dropped` notice already says why.

## Migration Plan

None: nothing recorded changes, and a run recorded since 0.2.0 shows its figures as soon as this ships.
