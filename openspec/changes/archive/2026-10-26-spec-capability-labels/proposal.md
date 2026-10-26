# Proposal

## Why

#169 decided that troupe's issues are labelled by capability, not by spec, and that each spec names the capability
labels it belongs to in one line under its Purpose (owner, 2026-10-26). None of troupe's 25 current specs has that
line yet. troupe-run/infrastructure#151's drift check will read it instead of needing a `cap:<folder>` label for every
spec folder, and is blocked until the line is there (#170).

## What Changes

- **Each spec in `openspec/specs/` gets a `Capability:` line** as the first line of its `## Purpose` section, naming
  the labels #169's mapping gives it, for example ``Capability: `cap:stages`, `cap:vcs` ``. The Purpose's prose is
  unchanged. The 25 specs and their labels:

  | Spec | Labels |
  |---|---|
  | `actor-runners`, `claude-code-runner`, `scripted-runner` | `cap:actor-runners` |
  | `runner-protocol` | `cap:actor-runners`, `cap:protocol` |
  | `stages` | `cap:stages` |
  | `run-workspaces` | `cap:stages`, `cap:vcs` |
  | `config` | `cap:config` |
  | `config-files` | `cap:config`, `cap:projections` |
  | `artifact-store` | `cap:storage` |
  | `client-protocol` | `cap:core-api`, `cap:protocol` |
  | `flake-hunt`, `python-support`, `quality-check`, `releases` | `cap:development` |
  | `docs-publishing` | `cap:development`, `cap:user-docs` |
  | `cli`, `event-store`, `identity`, `lineage`, `platform`, `policy`, `protocol`, `runs`, `user-docs`, `vcs` | its own label (`cap:cli`, `cap:event-store`, …) |

- **`openspec/config.yaml`'s context says a new spec names its labels the same way.** The context reaches every
  proposal, so a new spec's labels are named when it's proposed, where troupe-run/infrastructure#153's guard will
  look for them.

Nothing under `openspec/changes/archive/` changes: the archives record what was built and stay as they are (owner,
2026-10-26). The labels themselves (adding `cap:development`, folding the spec-level ones, relabelling issues) are
troupe-run/infrastructure#151's.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. No requirement changes. The line is metadata in each spec's Purpose, and OpenSpec ignores a delta's Purpose for
a spec that already exists, so the line can't travel as a delta anyway (design D1). The change sets
`skip_specs: true` and edits the 25 main specs directly.

## Impact

- Changed: `openspec/specs/*/spec.md` (25 files, one line each plus a blank line), `openspec/config.yaml`. No code,
  tests or docs change.
- The commits need only the OpenSpec part of the check: every changed path is under `openspec/**`.
- **troupe-run/infrastructure's drift job reports 25 changed Purposes** from this change's merge until #151 lands.
  Its Purpose check compares each spec's whole Purpose with the text recorded in `oob/troupe-spec-purposes.json`,
  and #151 already plans to reconsider that check (design D4).
- Follow-ups: troupe-run/infrastructure#151 (reads the line, relabels) and #153 (checks it at proposal).
- Rollback: revert the commit.
