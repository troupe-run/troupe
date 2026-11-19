# Design

## Context

The delivered `scripts/quality_gates.py` (troupe-run/infrastructure#349, change `gate-files`) has a `size` subcommand,
reads an optional `[size]` table (`block_above`, `warn_above`, `exclude`, `[size.allow]`), and leaves out of every gate
the paths `.github/guard-delivery.json` lists. It measures text files only, counting CRLF as LF, and judges only files
the work adds or changes since the base. troupe's `quality-gates.toml` and `pyproject.toml` still list the delivered
files by hand, and miss the newly delivered `scripts/quality_audit.py`.

## Goals / Non-Goals

**Goals:** declare the owner's limits; run the gate on every check; drop the patterns the delivery list now covers.

**Non-Goals:** splitting any file (#471 to #477 do that); changing the gate itself (infrastructure owns it).

## Decisions

### D1. Limits and exclusions as infrastructure declares them

`block_above = 49152`, `warn_above = 32768` (owner, 2026-11-19). `exclude` is `**/fixtures/**`,
`openspec/changes/archive/**` and `uv.lock`: fixtures are recorded data, archived changes are never edited, and the lock
file is generated. Binary files are never measured. This matches infrastructure's own declaration, less its tofu state,
which troupe doesn't have.

### D2. Each ceiling is today's size, rounded up to a whole KiB, plus 16 KiB

As infrastructure computed its own (`scripts/guard.py`: 205,573 bytes → 201 KiB → 217 KiB = 222,208). Measured on this
branch, on 2026-11-20:

| File | Bytes | Ceiling | Split issue |
|---|---|---|---|
| `protocol/schemas/error.schema.json` | 70,680 | 88,064 | #471 |
| `packages/troupe/src/troupe/protocol/error.schema.json` | 70,680 | 88,064 | #472 |
| `contributing/runners.md` | 67,684 | 84,992 | #473 |
| `packages/troupe/tests/test_run_host.py` | 66,733 | 83,968 | #474 |
| `openspec/specs/runner-protocol/spec.md` | 54,744 | 71,680 | #475 |
| `packages/troupe/tests/test_platform_processes.py` | 53,388 | 70,656 | #476 |
| `openspec/specs/openai-runner/spec.md` | 51,218 | 68,608 | #477 |

`test_platform_processes.py` grew from 52,812 bytes since #478 was written (#478 listed 69,632), so its ceiling is
one KiB higher: the brief is "its current size + 16 KiB". Every other figure matches #478. Each entry carries its split
issue as a comment. The gate fails on an entry whose file is gone or under 49,152 bytes, so a split removes its entry in
the same pull request.

### D3. The size step runs right after complexity, with the same base

Both are diff gates judged against `--base`, cheap, and run on every check, scoped or full; putting size next to
complexity, before the tests, makes an oversize file fail fast. It takes `--base` exactly as complexity does.

### D4. Delivered files: only the delivery list

`[complexity] exclude` keeps `**/tests/**` and the generated config models; `[tool.coverage.run] omit` keeps
`*/tests/*`. Coverage.py then traces the delivered scripts too, but the coverage gate drops each delivered path before
it measures a package, so `scripts`' figure, its baseline 88.4, is unchanged. Verification runs each gate on a branch
that touches every delivered file and checks none is judged.

## Risks / Trade-offs

- A pull request that edits a file between 32 and 48 KiB gets a note on every check. That's the intended nudge, never a
  failure.
- If the delivery list ever lost an entry, the file would be measured again: that's infrastructure's list to keep, and
  the gate refuses an unreadable one rather than measuring everything.
