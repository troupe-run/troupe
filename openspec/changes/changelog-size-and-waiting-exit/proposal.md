# Proposal

## Why

The 0.4.0 release pull request (#533) fails every CI leg. Its changelog entry grows `packages/troupe/CHANGELOG.md` from
48,910 to 49,990 bytes, past the size gate's 49,152 (#535). Only release-please writes changelogs, and every release
adds to them, so no release of core can pass once the file is at the limit. Separately, since gates (0.4.0) a
newcomer's first `troupe perform` exits 4, which shells and CI read as failure. Neither perform's message nor the
walkthrough says otherwise plainly. The owner decided both on 2026-11-27: exclude generated changelogs from the size
gate, and keep exit 4 but make it unmistakable.

## What Changes

- `quality-gates.toml`'s `[size] exclude` gains `**/CHANGELOG.md`, so the size gate doesn't measure a component's
  changelog, as it already doesn't measure fixtures, archived changes or `uv.lock`.
- When `troupe perform`'s run succeeds and its work waits at its gate, the message on standard error says the run
  succeeded and that its work waits for the role. It also says that exit 4 means waiting, not failure, and still
  names the worktree and `troupe diff`, `troupe approve` and `troupe reject`.
- The first-run walkthrough (`docs/opening-night/first-performance.md`) says plainly that exit 4 means the run
  succeeded and waits for you, not that it failed. The CLI reference's exit-code table already says this. A test
  checks that the two agree.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `quality-check`: the size gate doesn't measure generated changelogs.
- `cli`: perform's message for a run waiting at its gate says the run succeeded and that exit 4 means waiting.
- `user-docs`: the first-run walkthrough says exit 4 means waiting, not failure.

## Impact

- `quality-gates.toml` (one exclude pattern). No other repository is affected: each repository keeps its own
  thresholds (troupe-run/infrastructure spec: quality-gates). The gate's code is delivered from infrastructure and
  doesn't change.
- `packages/troupe/src/troupe/cli/commands.py` (`_settle_hint`'s waiting branch) and its unit tests.
- `docs/opening-night/first-performance.md` and the docs tests.
- After this merges, release-please rebuilds #533, which should then pass.
