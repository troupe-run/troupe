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

**D3. The capture tool is tested end to end with the engine stand-in.** Importing the tool for the round-trip
check put it in `runner-mistralrs`'s coverage, where its untested `capture()` measured 48% and pulled the plugin to
84.2%, 3.8 below its baseline, so the merge queue's coverage leg failed. The owner chose to test the tool rather than
drop the check or loosen the gate. A test runs `capture()` and `main()` with the module's temporary directories
fixed, `engine.load` serving each fixture's recorded responses through the stand-in, and the output directory under
the test's own, then checks `run.json`, `responses.json`, `engine.json` and `expected.json` come out as recorded.
- *Alternative: drop the round-trip check.* That brings the plugin back to 88.1%, but nothing would then stop a
  capture writing what the replay doesn't compare.
- *Alternative: leave `tools/` out of coverage, or lower the baseline.* That loosens a gate.

The test found that the tool recorded a Windows capture's token counts under the wrong keys. The tool definitions
are counted as JSON, which doubles a Windows path's backslashes, and the tool put only the path as written in its
placeholder. It now puts the JSON-written path in the placeholder too, as the stand-in reads it.

## Risks / Trade-offs

- [The replay replaces the version only on the `init` event] → That's the only event that carries `runner`. The
  check finds the `init` by its type and fails if it's missing, rather than skipping silently.
