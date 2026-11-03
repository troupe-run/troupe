# Proposal: actors declare their effects, and runners apply them

Issue: troupe-run/troupe#241. Decided in #239. Builds on #240 (the runner SDK, `troupe_plugin_sdk.effects`). Blocks
#56 and #162. A stage that enforces effects (#65) reads the same declaration later.

## Why

#239 decided that troupe's own scheme for what an actor may change is the actor's **declared effects**, not Claude
Code's permission rules. #240 built the check (`Effects`: `write`, `delete` and `move` path patterns, read-only when
nothing is declared) into the SDK's tools, but an actor can't declare effects yet, and nothing reaches a runner. The
local-model runner (#56) needs both before it can let a model change a file.

The owner settled the open parts on 2026-11-03:

- **`expect` must be covered by the declaration.** An `expect` path that no effect allows is invalid config.
- **After a run, troupe checks both directions:** that what was expected changed, *and* that nothing changed outside
  what was declared. This applies to every runner, so it backs up whatever the runner did during the run.
- **Runners get ephemeral scratch space** that isn't an effect, so no actor has to declare something like
  `write: /tmp/**` to work.
- **The Claude Code runner maps the declaration onto its own permission rules**, built so that any runner can plug
  in its own way of applying the same declaration.

## What Changes

- **An actor declares `effects`** in `.troupe/actors/<name>.yaml`: a group of three lists, `write`, `delete` and
  `move`, of theatre-relative path patterns in the SDK's pattern language, each set with `troupe config set`
  (`actors.tester.effects.write='["out/**"]'`). Absent, or an empty list, declares nothing: **with nothing declared,
  an actor is read-only.** A malformed pattern, or one under `.git/` or `.troupe/`, is refused naming it.
- **BREAKING: every `expect` path must be covered by a `write` or `move` pattern,** or the actor is invalid. An
  existing actor whose `expect` isn't covered is refused with `config.invalid`, naming the path and the
  `troupe config set` that fixes it.
- **BREAKING: the post-run effect check also audits what changed.** Every file the run added, changed or removed in
  its workspace, as git sees it, must be allowed by the declaration: added or changed needs `write`, removed needs
  `delete`, and a file that moved needs `move` for both ends. A change outside the declaration fails the check and
  the run, naming each path and the effect it would have needed. `expect: []` no longer means "no effect check": it
  means no file has to change, and the audit still runs. troupe's own `.troupe/` and the scratch space are outside
  it.
- **Run start carries the effects and a scratch directory** (runner contract, version 0, changed in place). troupe
  makes a scratch directory for each run outside the workspace, passes its path, and removes it when the run ends.
  Nothing written there reaches the theatre or needs an effect.
- **Each runner applies the effects its own way, and says how.** The `init` event names how the runner applied them:
  `checked` (each tool call checked before it runs, as the SDK's tools do) or `translated` (into its engine's own
  rules). The SDK gives runners the parsed declaration and a small, framework-free translation interface, so a
  runner plugs in its own mapping.
- **The SDK's tools take scratch paths and keep away from `.troupe/`.** A tool may read and write an absolute path
  inside the run's scratch directory without any effect. No tool changes anything under the workspace's `.troupe/`,
  whatever the effects allow, as with `.git`.
- **The Claude Code runner translates the effects into permission rules** in the settings file it already writes:
  `write` into rules for its file-editing tools, plus the scratch directory. **BREAKING:** options that would let
  Claude Code change files the declaration doesn't allow are refused: `permissionMode` values that approve edits
  without rules, and `allowedTools` rules for its file-editing tools. Claude Code has no tool of its own for
  deleting or moving, so when either is declared the runner offers troupe's own `Delete` and `Move`, checked by the
  SDK, as tools of a small MCP server it ships.
- **The scripted runner gets a `tool` step,** which carries out a tool call through the SDK's tools with the run's
  effects and scratch. With it, `troupe perform` shows the done-when end to end, without a model: a read-only actor
  can read but not write, and an actor can write, delete or move only where it declares.
- **The auditions declare their effects:** the scripted actor writes `out/hello.txt`, so it declares that; the
  Claude Code actor declares `write: ["**"]`, so any direction that edits files still succeeds.
- **Lineage still records the local stage's effects as `unenforced`.** Neither a runner's check nor the audit is
  enforcement (spec: stages).
- **Docs follow:** the config schema page (generated), the actor's effects in the user docs, the Claude Code
  runner's README, and the runner guide for plugin authors.

Not in this change: a stage that enforces effects (#65); the local-model runner (#56) and the OpenAI-style runner
(#162); network effects; refusing `troupe accept` for a run whose audit failed (it's still the person's call, after
`troupe diff`).

## Capabilities

### New Capabilities

- `effects`: what an actor's declared effects are and mean across troupe: their form, the read-only default, how
  `expect` must sit inside them, the post-run audit of what changed, the scratch space every run gets, and that none
  of it is enforcement.

### Modified Capabilities

- `config`: the actor gains `effects`; `expect` must be covered by it; `expect: []` no longer means no check; the
  auditions declare effects; the Claude Code audition's options change.
- `runner-protocol`: `run/start` carries `effects` and `scratch`; `init` says how the runner applied the effects.
- `runner-tools`: tools reach the scratch directory without an effect; `.troupe/` is out of reach for changes.
- `plugin-sdk`: the SDK parses the declaration from run start and offers the translation interface runners plug into.
- `actor-runners`: success needs the audit to pass as well as the expected files.
- `runs`: perform passes the declaration and a scratch directory, and removes the scratch directory when the run ends.
- `claude-code-runner`: effects become permission rules; options that would widen them are refused.
- `scripted-runner`: the `tool` step.
- `stages`: the audit, like the effect check, isn't enforcement.

## Impact

- **Protocol:** `protocol/schemas/config/actor.schema.json` (`effects`, the pattern), `runner/run-start.schema.json`
  (`effects`, `scratch`), `runner/run-event.schema.json` (`init.effects`). A protocol change, released as one.
- **SDK:** `effects.py` (from run start, `.troupe/`, the translation interface), `tools.py` (scratch, `.troupe/`),
  `runner.py` (the new fields).
- **Core:** `config/kinds.py` (effects and `expect` coverage), generated config types, `runners/effects.py` (the
  audit, combined with the expected files), `runners/host.py` and `conformance.py` (run start's fields),
  `runs/perform.py` (scratch's life), `workspaces.py` and the VCS port (what changed, for both workspaces),
  `audition.py`, `defaults.py` (the scratch setting).
- **Plugins:** `runner-claude-code` (translation, options checks, README, schemas), `runner-scripted` (`tool` step,
  options schema).
- **Docs:** `docs/prompt-book/config-schema.md` (regenerated), user docs on actors, `plugins/README.md`,
  `contributing/runners.md`.
- **Infrastructure:** a new spec, `effects`, so `oob/troupe-spec-purposes.json` gets its Purpose in an
  infrastructure pull request; it uses the existing `cap:effects` and `cap:config` labels.
- **Existing theatres:** an actor whose `expect` isn't covered, or a Claude Code actor using `acceptEdits`, must be
  changed before it runs again. Pre-alpha, with no compatibility promise; the errors name the fix.
