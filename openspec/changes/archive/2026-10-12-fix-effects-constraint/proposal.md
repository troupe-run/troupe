# Proposal

Issue: #46. Decisions: #3 (effects on a local stage: option C), #37 (plugin transports).

## Why

The project context, changed in #42 for #39, says *"Declared effects are enforced on code that runs over JSON-RPC."*
That overclaims. Running over JSON-RPC enforces nothing by itself: a JSON-RPC runner on a local stage runs as the
user, with the whole disk and network. #37 already says "neither transport is a sandbox: stages and policy decide
what code can touch", and #3 (decided 2026-10-12, option C) says what actually happens on a stage that can't
enforce. A proposal written against the current line would assume enforcement the system doesn't have.
`plugins/README.md` says the same thing ("so declared effects can be enforced on them").

## What Changes

- **`openspec/config.yaml`, the pluggable-extensions line** becomes:
  > - Stages (sandboxes), actor runners, notification channels and guests are pluggable. Declared effects are
  >   enforced by a stage that can enforce them. A stage that can't refuses the actor unless policy allows it, and
  >   lineage records that its effects weren't enforced.

  The transport line ("In-process code is trusted and its effects aren't enforced … Neither transport is a sandbox:
  stages and policy decide what code can touch") already matches, and is unchanged.
- **`plugins/README.md`, the opening paragraph** becomes:
  > Out-of-process plugins: actor runners, stages, guests and notification channels. **They run over JSON-RPC, ours
  > included**, so a stage that can enforce declared effects can enforce them on a plugin, and a plugin can be
  > written in any language (decision #37). Running out of process isn't a sandbox by itself: what a plugin can
  > touch is up to the stage it runs on, and policy (decision #3).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None: project context and documentation only. The change declares `skip_specs`. #3's behaviour (the refusal, the
policy setting, the lineage record) is specified by #36, which builds the local stage.

## Impact

- `openspec/config.yaml` (one line of the `context:` block) and `plugins/README.md` (its opening paragraph).
- No code, spec or behaviour change.
- #36 (`perform-status-logs`, in progress in its own worktree) touches neither file, as far as its issue describes.
  If it does, whichever lands second rebases.
