# Design

## Context

See proposal.md, "Why". The replay's `_normalised` already swaps the run id for `<run>` and the replay's paths for
`<workspace>` and `<scratch>`. The capture tool's `normalised` does the same when it writes `expected.json`, and
`<model>` goes in as the model name. The runner version is the only value in `expected.json` that a release changes.

## Goals / Non-Goals

**Goals:**
- A release-please version bump changes no mistral.rs fixture and fails no replay.
- The replay still fails if the runner reports anything other than its installed package's version.

**Non-Goals:**
- Changing what the runner reports, or any other runner's tests. The anthropic, openai and ollama replays already
  check and replace the version. claude-code's replay overwrites the version with its recorded `unreleased` before
  comparing.
- Re-capturing the fixtures. This needs no model, and only the one value changes.

## Decisions

**D1. Check against the installed version, then compare as `<package version>`.** The replay asserts that the `init`
event's `runner.version` equals `importlib.metadata.version("troupe-runner-mistralrs")`, then replaces it with
`<package version>` before comparing with `expected.json`. This is the same check and the same placeholder text that
`anthropic_fixture_replay.py` and `openai_fixture_replay.py` use, and ollama's replay works the same way.
- *Alternative: only normalise it, like `<run>`.* A runner that reported a wrong or hard-coded version would then
  pass. The assertion keeps that covered, at the cost of one line.
- *Alternative: keep the literal and fill in the installed version when loading `expected.json`.* That also works,
  but the fixture would still record a version that's out of date after every release, and it would differ from the
  other runners' fixtures.

**D2. The capture tool writes the placeholder.** `capture_mistralrs.py` swaps the `init` event's runner version for
`<package version>` when it writes `expected.json`. Otherwise the next capture would bring the literal back and the
next release would fail again.

## Risks / Trade-offs

- [The replay replaces the version only on the `init` event] → That's the only event that carries `runner`. The
  check finds the `init` by its type and fails if it's missing, rather than skipping silently.
