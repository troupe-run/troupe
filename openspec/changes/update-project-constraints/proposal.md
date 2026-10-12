# Proposal

Issue: #39. Decisions: #37 (plugin transports), #9 (the safety rule, owner 2026-10-12), #1 and #35 (lineage: the
correlation ID and the cause).

## Why

`openspec/config.yaml`'s `context:` block is the project context every OpenSpec artifact is written against. Three
decisions taken on 2026-10-12 replaced or sharpened rules it still states the old way. Proposals and designs written
from now on would reason from a rule that no longer holds: the event-store design (#35) had to argue its way round
"third-party code only ever runs out of process" before #37 replaced it. `plugins/README.md` repeats the same old rule.

## What Changes

- **Plugin transports (#37).** The fixed constraint "Third-party code only ever runs out of process" is replaced
  with #37's wording. Every port is defined in core, with a direct and a JSON-RPC transport. What ships with troupe
  runs direct, and plugins acquired by config run over JSON-RPC. In-process plugins are trusted and their effects
  aren't enforced. Policy can restrict which transports are allowed. Neither transport is a sandbox: stages and
  policy decide what code can touch.
- **Two neighbouring constraints are brought in line with #37:**
  - "Declared effects are enforced" becomes enforced for plugins that run over JSON-RPC, on the stage they run on.
  - The repo-layout line says `packages/` holds what ships with troupe and runs direct, and `plugins/` holds
    JSON-RPC plugins.
- **Malformed input is an error (#9).** A new rule next to "Refuse rather than guess": a malformed or ambiguous
  input is an error that names the input and the fix, never a quiet fall-through to a default. Only an absent input
  may fall through.
- **Lineage (#1, #35).** "change id" becomes the correlation ID that one command's events share, and that events
  recorded in reaction to them inherit, plus the cause: the command, or the event an event was recorded in reaction
  to.
- **`plugins/README.md`**: its opening paragraph and its paragraph on in-process adapters say the same as #37,
  instead of "third-party code only ever runs out of process".

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. `config.yaml` is project context and `plugins/README.md` is documentation; neither is a spec requirement. The
change declares `skip_specs`.

## Impact

- `openspec/config.yaml` (the `context:` block only) and `plugins/README.md`.
- No code, spec or behaviour changes. The in-flight changes #34 (runner contract) and #35 (event store) already
  follow these decisions.
- `plugins/README.md` is also edited by #34, in other paragraphs; whichever change lands second rebases (design.md).
- Out of scope: #38's open questions (plugin acquisition), and the org-default templates
  (troupe-run/infrastructure#15).
