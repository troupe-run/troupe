# Design

## Context

A runtime resolves its own values field by field, with the person's environment over the theatre's config over
troupe's built-ins (runtimes spec, "The person's environment overrides a runtime's values"). A run's model then
combines that resolved model with the actor's `model`. Today the combination puts the runtime's model first when it
came from the environment, then the actor's, then the rest of the runtime's (`run_model` in `core/runtimes.py`). See
proposal.md for why that order changes.

## Goals / Non-Goals

**Goals:**

- The actor's own model wins, the environment's comes next, and the runtime's in config comes last, with a test for
  each level winning over the one below it, each written to fail on main first.

**Non-Goals:**

- How a runtime resolves its own values doesn't change. `troupe config get --resolved runtimes.<name>` still shows
  the variable's model with source `env`, since that is the runtime's model as this person resolves it. Only a run
  whose actor sets a model differs.
- No notice when a variable is set and an actor's model beats it. Every run already records its model's source, and
  `troupe perform --rehearse` shows it, so the person can see which won. A notice can follow if people trip on it.
- No compatibility form for the old order: troupe is pre-1.0 and keeps no old behaviour behind a flag.

## Decisions

**D1. Only the combination changes, in the one function that makes it.** `run_model` takes the actor's model first,
then the resolved runtime's model whatever its source. The runtime's resolution stays as it is, so `config get
--resolved`, the fit check (`runtime.unfit`), which judges the runtime as resolved, and pricing, which prices whichever
model the run uses, are unchanged. The alternative, threading the actor's model into `resolve`, would make a runtime's
resolved values depend on which actor asked, and `config get --resolved` has no actor.

**D2. The old requirement is removed and the new one added under its new name.** The requirement's name states the
order, so it can't be kept. OpenSpec refuses a MODIFIED block that drops a scenario ("The person's override wins" is
now false) and refuses REMOVED plus ADDED under one name, so the requirement is removed and added as "The run's model
comes from the actor, the environment, then the runtime". Its scenarios are one per level winning over the next, plus
the unchanged refusal when nothing sets a model. The price requirement keeps its scenario names, and "The model from
the environment has no price" now has an actor that sets no model, since the environment's model can't reach a run
otherwise.

**D3. Nothing new is recorded.** The issue asks to record the model's source if it's cheap. It's already done: a
run's start records its runtime's model with its source (runs spec, "A run's start records its runtime and where each
value came from"), and the source is `actor`, `env` or `theatre`. The new tests check the source as well as the value.

**D4. Docs are split with the 0.2.0 docs change (#460) by file.** This change updates what is generated from or
next to the code: the actor schema's `model` description (and so its packaged copy, the generated config models and
`docs/prompt-book/config-schema.md`), the help text of `troupe config get --resolved` if it states an order, a
docstring in `defaults.py`, and the Ollama runner README's sentence on the order. #460 updates the user pages
(`docs/stagecraft/runtimes.md`, `contributing/config.md`, the mistralrs README, `bring-your-own-agent.md`) and rebases
on this change, as agreed with its author on 2026-11-18. Whichever merges second regenerates the generated files.

## Risks / Trade-offs

- [A person relies on the variable to try another model on an actor that sets one] → They now set or unset the
  actor's model instead. The runtimes spec's REMOVED requirement says so, and the docs change says it for users.
- [`troupe init`'s mistralrs actor stops picking up `TROUPE_RUNTIME_MISTRALRS_MODEL`] → It sets no model (its model is
  a path on the person's machine), so the variable still reaches it. A test of the mistralrs setup already covers
  this; the implementation checks it still passes.
