# Proposal

## Why

The 0.2.0 release PR (#263) fails on every CI leg. All four mistral.rs fixtures (`effects-refused`, `length-stop`,
`tool-call`, `two-calls`) fail to replay, because each one's `expected.json` records the `init` event's runner
version as `0.0.0`. That is main's package version, and release-please bumps `troupe-runner-mistralrs` to 0.1.0. The
runner reports the installed package's version, so every release breaks the fixtures. Fixes troupe#468.

## What Changes

- The mistral.rs fixture replay checks that the `init` event's runner version is the installed
  `troupe-runner-mistralrs` version, then compares it as `<package version>`. The anthropic, openai and ollama
  replays already work this way.
- The four fixtures' `expected.json` record `<package version>` in place of `0.0.0`.
- The capture tool (`tools/capture_mistralrs.py`) writes `<package version>` too, so a fresh capture matches the
  replay.
- No runner code changes. The runner still reports its installed package version.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. The `mistralrs-runner` requirement "Fixtures pair real engine output with protocol events" is unchanged. The
version placeholder is a test detail, like `<run>`, `<workspace>` and `<model>`. The change sets `skip_specs: true`.

## Impact

- `plugins/runner-mistralrs/tests/test_mistralrs_fixtures.py`, `plugins/runner-mistralrs/fixtures/*/expected.json`
  and `plugins/runner-mistralrs/tools/capture_mistralrs.py`. Test and tooling only, so it uses a `test:` commit and
  release-please sees no release-bearing change.
- Unblocks release PR #263. Once this lands on main, release-please regenerates #263 from main.
