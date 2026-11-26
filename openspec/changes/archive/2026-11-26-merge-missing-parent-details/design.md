# Design

## Context

Two places raise `events.missing-parent`: the text store, for streams it reads with a single head (`select`, recording),
and config's merge, for the config stream, which it reads through `history()` (it refuses nothing, config-model design
D5). The store's error carries `line`, `event`, `missingParent` and `onlyIn`; merge's carries only the last two, so it
fails `error.schema.json`. Nothing tests merge's raise, so the protocol guard never saw it.

## Goals / Non-Goals

**Goals:** merge's error matches the schema and is reached by a test under the protocol guard.

**Non-Goals:** filling `onlyIn` from merge. Only the store knows which segments are invisible on this branch; merge
sees `RecordedEvent`s, so `onlyIn` stays `[]` there (allowed by the schema). Changing the event port to expose it is a
larger change than this bug.

## Decisions

- **D1: keep merge's check, add the two details.** Removing it in favour of the store's would need `history()` to
  refuse, which config-model D5 rejects, or config to call another store method first. Keeping it is the smaller,
  already-designed path. `line` is `record.line`, `event` is `record.id`, as the store's `_missing_parent`.
- **D2: test it through the real store.** An integration test records config twice in a git theatre (two segments),
  removes the first segment, and reads config. That shows the check is reachable by a real store, not only by a
  hand-built history, and the protocol guard validates the error as it's constructed. A unit test of `merge` with an
  in-memory history covers the same details for mutation runs, which see unit tests only.

## Risks / Trade-offs

- [Two raise sites can drift again] → both are now under a test the protocol guard watches, so a missing key fails a
  test.
