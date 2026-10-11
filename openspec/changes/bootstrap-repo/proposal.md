# Proposal

Issue: troupe-run/troupe.run#18

## Why

The repo is empty apart from OpenSpec, and every later change (starting with the walking skeleton) needs a place
to land: a package layout whose boundaries are enforced, quality gates that run the same locally and in CI, and the
first pieces of the two seams everything else depends on (the CLI surface and the OS seam). Setting these up first,
on their own, means later changes add behaviour instead of inventing structure, and the bake-off's lesson (lint
findings grew 8 → 34 when nothing checked them) is designed out from the first commit.

## What Changes

- A uv workspace with three kinds of member, each with a fixed rule about what it may import:
  - `packages/` — in-process, first-party distributions loaded via Python entry points. `packages/troupe` holds the
    core, the house (later) and the CLI. Adapters (storage, VCS, identity) arrive later as their own packages.
  - `plugins/` — out-of-process plugins that speak JSON-RPC over stdio and import only `protocol/`. Empty in this
    change except for the layout and its import rule.
  - `protocol/` — language-neutral contracts (JSON Schema). Holds the error shape in this change.
- Quality gates: ruff (lint and format), `mypy --strict`, pytest with hypothesis, and import-linter contracts that
  turn a boundary violation into a failure.
- CI on GitHub Actions: Linux, macOS and Windows are all required checks. Windows is supported from the first
  commit rather than retrofitted before 1.0 (Decision #17, revised 2026-10-11).
- Developer Certificate of Origin (DCO) sign-off checks, so every contribution is certified under Apache-2.0
  from the first outside PR. This replaces the CLA the site used to promise (design D10).
- A minimal CLI: `troupe --version`, global flags accepted anywhere, and errors rendered from structured data with
  documented exit codes.
- The first parts of the `platform` seam: atomic file replacement, a lock that never waits silently or
  indefinitely, and friendly path display.

## Capabilities

### New Capabilities
- `cli`: the command-line surface as a thin client — invocation, global flags, how structured results and errors
  are rendered, and exit codes.
- `platform`: the single seam for OS-specific behaviour — atomic writes, locking with timeouts, and path display.
  Later: processes and signals, daemon IPC, file watching.

### Modified Capabilities
None (no existing specs).

## Impact

- New files: `pyproject.toml` (workspace root), `packages/troupe/`, `plugins/README.md`, `protocol/`,
  `.github/workflows/`, DCO check configuration, `uv.lock`.
- Dependencies (dev only, except where noted): ruff, mypy, pytest, hypothesis, import-linter, jsonschema (to test
  that error output matches the protocol schema). No runtime dependencies beyond the standard library are expected
  for this change; the design names any that become necessary.
- Closes nothing on its own; implements the CI part of #17 and the layout agreed in the exploration of 2026-10-11.
