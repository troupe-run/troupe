# Design: actors declare their effects, and runners apply them

See [proposal.md](proposal.md) for why. Behaviour is in the specs: the new [effects](specs/effects/spec.md) spec, and
the deltas to config, runner-protocol, runner-tools, plugin-sdk, actor-runners, runs, claude-code-runner,
scripted-runner and stages.

## Context

- **The SDK already checks effects.** `troupe_plugin_sdk.effects.Effects` holds `write`, `delete` and `move` pattern
  lists, compiled by the SDK's own matcher (`pattern_regex`), read-only by default. `Tools(workspace, effects)`
  checks every call. Nothing builds an `Effects` from config yet, and `run/start` has no field for one.
- **The actor** is `protocol/schemas/config/actor.schema.json` (`runner`, `options`, `expect`, `workspace`), with
  types generated from it. `troupe.core.config.kinds.actor_problems` validates an actor: the schema, then the
  runner's options schema. Problems surface as `config.invalid` at set and at perform.
- **The effect check** is a port, `troupe.core.runners.effects.EffectCheck` (`before()`, `after()` →
  `EffectVerdict`), with `ExpectedFiles` and `NoEffectExpected`. `perform` picks one from `expect`
  (`runs/perform.py`, `effect_check_for`).
- **Worktree runs** already capture a git diff against their base commit when they end, leaving `.troupe/` out and
  counting what was left out (run-workspaces spec). Theatre runs capture nothing.
- **The Claude Code runner** writes a private settings file (`permissions.allow`/`deny` from `allowedTools` and
  `disallowedTools`) in a 0700 directory outside the workspace, and passes `--permission-mode` only when set.
- **Claude Code's permission model** (read from code.claude.com/docs on 2026-11-03: permissions, permission modes,
  sandboxing, tools reference, MCP):
  - `Edit(path)` rules cover every built-in file-editing tool (`Write(…)`, `NotebookEdit(…)` and `MultiEdit(…)`
    rules never match). Paths use gitignore syntax: `//abs` is absolute, `/x` is relative to the settings file, bare
    is relative to the cwd. A Windows path is normalised to `/c/Users/…`, so it's written `//c/Users/…`.
  - Deny, then ask, then allow; the first match wins, and an allow can't carve an exception out of a deny.
  - `dontAsk` denies every call that would prompt: only reads in working directories, read-only shell commands and
    calls an allow rule covers run. `acceptEdits` approves edits **and `rm`, `mv`, `cp`, `mkdir`, `touch`** anywhere
    in the working directory with no rule. `bypassPermissions` ignores allow rules. `auto` is a classifier.
  - There's no built-in delete or move tool: only Bash or PowerShell. The sandbox covers shell commands only, can't
    tell deleting from writing, isn't available on native Windows, and auto-allows sandboxed shell commands by default
    (`autoAllowBashIfSandboxed`).
  - MCP servers can be given with `--mcp-config` and `--strict-mcp-config` in `-p`; their tools are
    `mcp__<server>__<tool>` and need allow rules under `dontAsk`.

## Goals / Non-Goals

**Goals:**
- One declaration, written once in config, read the same way by every runner and, later, by a stage (#65).
- Two independent lines of defence: the runner applies the declaration during the run, and troupe audits the result
  after it, whatever the runner did.
- A runner-neutral seam, so each runner plugs in its own way of applying the declaration.

**Non-Goals:**
- Enforcement. Neither line contains the runner process; lineage stays `unenforced`.
- Network effects, read restrictions, or limits on scratch's size (nothing on the local stage could enforce them).
- Changing `troupe accept` or `troupe discard`. A run that failed its audit is kept like any failed run.

## Decisions

### D1. `effects` is a group of three lists in the actor, with one shared pattern definition

`effects: {write: [...], delete: [...], move: [...]}`, each list optional, all closed. An object in config is a group
and a list is one value (config spec), so `troupe config set actors.x.effects.write='["out/**"]'` works with no new
config machinery, and a merge treats each list whole.

The actor file holds it just after `expect`, so a file written before it existed keeps its layout, and the two
read together: what a run must change, then what it may.

The pattern is defined once, in a new `protocol/schemas/effects.schema.json` (`$defs/pattern`, `$defs/declaration`
with all three lists required, for `run/start`), and the actor schema references the pattern. Its ECMA-262 regex
encodes the SDK's rules (no empty part, `.`, `..`, `\`, `:`, control characters, leading `/`, `**` only as a whole
part) plus a first part that isn't `.git` or `.troupe`, and no control character anywhere (Python's `$` matches
before a trailing newline, so without it `"**\n"` would pass the schema and not the SDK). A hypothesis test checks that the schema's regex and
`pattern_regex` (plus the prefix rule) accept exactly the same strings, so the two can't drift.

- *Rejected: one list of `{effect, pattern}` entries.* Harder to read in YAML, and a reviewer scanning for `delete`
  should find it as a key.
- *Rejected: patterns in runner options.* Effects belong to the actor, whichever runner or stage runs it.

### D2. `expect` must sit inside `write` or `move`, checked with the actor

`actor_problems` gains a rule after the schema passes: each `expect` path must match a `write` or `move` pattern (a
move creates its destination; `delete` can't make a file exist). The problem's path is `actors.<name>.expect[i]`, its
fix the exact `troupe config set actors.<name>.effects.write=…` with the path added to what's there. Because it's an
actor rule, it applies at set, to merged config (where it makes a conflict, as other validation failures do), and at
perform (`config.invalid`), with no extra code path.

### D3. The audit is a second effect check, combined with the expected files

`EffectCheck` stays the port. A new `DeclaredEffects` check takes the declaration and a `ChangeSource` (below):
`before()` records the starting state, `after()` lists changes and classifies each:

| Change | Allowed when |
|---|---|
| added or modified | `write` matches it |
| removed | `delete` matches it |
| removed `a` + added `b`, same content id | `move` matches both, or `delete` matches `a` and `write` matches `b` |

Moves are paired greedily by content id, in path order, so the result is deterministic. A `Combined` check runs
`ExpectedFiles` (when `expect` isn't empty) and `DeclaredEffects`, and fails with one `effects.outside-declared` or
the existing missing-file error, or `effects.check-failed` holding both in `details` when both fail. `NoEffectExpected`
is then used only by tests and the conformance suite; `perform` always has the audit.

The error's `details.changes` is a list of `{path, change: added|modified|removed|moved, to?, needs}`, so every surface
can render it (CLI first).

### D4. What changed comes from the VCS port, as git sees it

The VCS port gains one query: `file_states(root, at=None) -> Mapping[str, str]`, every file version control would
record (tracked, plus untracked not ignored), path to a content id, leaving out `.git` and `.troupe/`. `at` names a
commit to read instead of the working tree.

- **Worktree run:** before = `file_states(worktree, at=base)`, after = `file_states(worktree)`. This counts committed
  changes, as capture does.
- **Theatre run:** before and after are both `file_states(theatre)`, taken just before the runner starts and just
  after it ends.
- **git adapter:** `git ls-files -s` gives blob ids for clean tracked files without reading them; only paths
  `git status --porcelain=v2 -z --untracked-files=all` lists as changed or untracked are hashed (`git hash-object`).
  Commit states come from `git ls-tree -r`.
- **files adapter:** walks the directory and hashes each file (sha256); it has no ignore rules, so it audits
  everything.

Content ids only need to be comparable within one adapter. Hashing is bounded by what git already reports as dirty, so
a large clean repository costs one `ls-files`.

- *Rejected: reusing the captured diff.* Capture is worktree-only, and its counts don't say which paths; parsing the
  diff for paths is more fragile than asking for states.
- *Rejected: an inotify-style watcher during the run.* OS-specific, and it misses what happened before it starts.

### D5. Run start carries `effects` and `scratch`; `init` carries `effects`

`run/start.params.effects` is the declaration with all three lists always present (D1's `$defs/declaration`), and
`params.scratch` an absolute path. `init.effects` is `checked | translated`, required. Version 0 changes in place
(runner-protocol spec); this pull request is the protocol change, released as one. The SDK's `RunStartParams` and
`InitEvent` gain the fields, the host fills them, and the conformance suite checks them.

**History stays readable.** Run events are recorded as they arrive, so an `init` recorded before this change has no
`effects`. The schema's `$defs/init` keeps `effects` optional, described as absent only in such a record; `$defs/event`
(what a runner sends) requires it, and `hostEvent` (what's recorded and shown) accepts both. The SDK mirrors the split:
`InitEvent.effects` may be None, and `parse_event`, which the host uses on a runner's events, refuses an `init` without
it, so `troupe logs` still reads an old run.

- *Rejected: `effects` optional in `run/start`, absent meaning read-only.* A runner that forgot to read it would look
  identical to one honouring a read-only actor. Explicit lists can't be misread.
- *Rejected: `init.effects` value `none`.* Every actor is at least read-only, so a runner that can't restrict
  anything doesn't conform. The audit still catches it, but the contract shouldn't describe it as allowed.

### D6. Scratch: made by the run host, outside the theatre, removed at the end

A named setting, `RUN_SCRATCH_ROOT` in `troupe.core.defaults` (None: the platform's temporary directory, through the
platform seam), holds per-run directories made with `mkdtemp(prefix="troupe-scratch-")` (0700 on POSIX). `run_actor`
makes one when the request names none, just before the runner starts, and removes it in a `finally` around the whole
run; a failed removal is a `run.scratch-not-removed` notice naming the directory. Owning it in the host, not in
`perform`, gives every caller a scratch directory (the conformance suite included) and keeps its life in one place.
`perform` refuses a root inside the theatre with `run.scratch-in-theatre` before anything is recorded; a theatre
inside the root is fine, since each run's directory is a new one made directly in the root.

Scratch isn't recorded in events: it's ephemeral by contract, and its path is host-specific (hosted deployments
address theatres by id). The runner learns it from `run/start` only.

- *Rejected: under `.troupe/local/`.* Inside the theatre, so in a theatre run it's in the workspace, and tools would
  see it as both.

### D7. SDK: the declaration, its normalised view, and the translation seam

`troupe_plugin_sdk.effects` gains:

- `Declaration(effects, workspace, scratch)` and `Declaration.from_run_start(params)`.
- `Declaration.absolute(effect) -> tuple[str, ...]`: each pattern rooted at the workspace, in POSIX form with a
  lowercase drive as its first part on Windows (`/c/work/out/**`), and `scratch_absolute()`. One function does the
  normalisation, behind the SDK's path seam, so every runner gets the same answer on every platform.
- `class EffectsTranslation(Protocol[T])`: `mode: Literal["checked", "translated"]` and
  `translate(declaration) -> T`. `Tools` is the `checked` implementation; the Claude Code runner's permission rules
  are a `translated` one. A future runner (a Codex-style sandbox, a container) adds its own without touching the SDK.

`Tools` also takes `scratch`: an absolute path that resolves inside it needs no effect; `Move` between scratch and the
workspace needs the workspace end's effect; links out of scratch are refused like links out of the workspace. Changes
under the workspace's top-level `.troupe` are refused like `.git`, but reads are allowed.

### D8. Claude Code: `dontAsk`, edit rules from `write`, troupe's MCP tools for `delete` and `move`

The translation (`troupe_runner_claude_code.permissions`):

- **Mode:** always `--permission-mode dontAsk`, or `plan` when the options ask for it. `acceptEdits`, `auto`,
  `bypassPermissions` and `manual` are refused with `claude-code.widens-effects`. `manual` would be equivalent in
  `-p` today, but only from Claude Code 2.1.302, so it's refused rather than trusted.
- **Write:** `Edit(//<abs pattern>)` allow rules from `Declaration.absolute("write")`, plus
  `Edit(//<scratch>/**)`. Deny `Edit(//<ws>/.git/**)` and `Edit(//<ws>/.troupe/**)`. Absolute rules avoid both
  gitignore's anchoring quirks for allow rules and the settings-file-relative `/x` form.
- **Scratch:** `--add-dir <scratch>`, and `TMPDIR`, `TMP` and `TEMP` pointed at it in Claude Code's environment. The
  runner's private directory (settings, character, MCP config) stays its own `mkdtemp`, never under scratch, so
  Claude Code can't edit its own settings.
- **Delete and move:** Claude Code has no tool for either, and shell rules match command text, not paths. When either
  is declared, the runner offers troupe's own `Delete` and `Move` through a small stdio MCP server it ships
  (`python -m troupe_runner_claude_code.effects_server`, standard library only, implementing `initialize`,
  `tools/list` and `tools/call`). The server runs the SDK's `Tools` with the declaration, so each call is checked
  exactly as in troupe's own runners. It's passed with `--mcp-config` (with `--strict-mcp-config`, already given),
  its tools allowed by `mcp__troupe__Delete` and `mcp__troupe__Move`. The declaration reaches it through a file in
  the private directory, not its command line.
- **Options:** `allowedTools` rules for `Edit`, `Write`, `NotebookEdit`, `MultiEdit` or `mcp__troupe` are refused;
  `disallowedTools` passes through (a deny only narrows). Shell rules stay the person's to allow, with a `log` warning
  that they can change files outside the rules and that the audit checks them. The settings file sets
  `sandbox.autoAllowBashIfSandboxed: false`, so turning on the sandbox from a loaded setting source can't
  auto-allow shell commands. A loaded `settingSources` gets a warning: its allow rules merge with the runner's.
- **Patterns Claude Code would read differently:** gitignore gives `[`, `]`, a leading `!` and a backslash meanings
  the SDK's patterns don't have, and a parenthesis would end the rule. A `write` pattern holding one, or a
  workspace or scratch path holding one (or a `*` or `?`, which would act as a wildcard there), is refused with
  `claude-code.untranslatable-pattern`, naming it, rather than escaped on trust. `delete` and `move` patterns
  aren't translated, since troupe's own tools read them, so they're kept as they are.
- **Where the widening check lives:** in the options parser, with the same rule in the published options schema
  (`permissionMode` is `dontAsk` or `plan`; `allowedTools` refuses editing tools and `mcp__troupe`), so `troupe
  config set` refuses a widening option when it's set, not at the next run.

- *Rejected: `Bash(rm <pattern>)` rules for delete.* Command-text matching misses `rm -f`, `find -delete`,
  `xargs rm`, and so on; it would claim a translation it can't keep.
- *Rejected: the sandbox for delete.* Shell only, can't tell delete from write, and not on Windows.
- *Rejected: refusing every Claude Code actor that declares delete or move.* It would leave Claude Code unable to
  delete at all, without a shell rule that the audit then fails.

### D9. The scripted runner's `tool` step is the fake model

`{"tool": "Write", "input": {...}, "callId"?: "c1", "isError"?: true}` runs through the SDK's `Tools` with the run's
declaration, and sends the SDK's `tool_call` and `tool_result` events (seq continues the runner's). A mismatch with
`isError` ends the run with an error result naming the step index. With it, `troupe perform` shows #241's done-when
end to end, without a model, on every platform in CI: read-only can read and not write; `write` writes only there;
`delete` and `move` each only where declared. The existing `write` step stays raw, to test that the audit catches
writes a runner didn't check.

### D10. The auditions declare their effects

The scripted audition declares `effects.write: ["out/hello.txt"]` (its `expect`). The Claude Code audition declares
`write: ["**"]`, drops `permissionMode: acceptEdits`, and keeps `allowedTools: [Read, Glob, Grep]`; "any direction
can succeed" still holds for edits, but deleting a file now fails the audit, which is the point.

## Risks / Trade-offs

- **[Changes outside the workspace are neither prevented nor detected]** → On the local stage, a Claude Code shell
  rule, the runner process itself, or a faulty runner can write anywhere the person's account can (`~/.bashrc`,
  `~/.ssh/config`), and the audit, which reads only the workspace, never sees it. The declaration limits what
  troupe's tools and Claude Code's rules allow; the audit verifies the workspace; neither is containment. The effects
  spec makes troupe say so in the local stage's refusal and in the docs, and a stage that enforces effects (#65)
  makes such writes ephemeral, lost with the container.
- **[Theatre runs audit concurrent edits as the run's]** → The error says so, and nothing is lost: the audit only
  fails the run, it never reverts. Worktree runs, the default, aren't affected.
- **[Ignored files are outside the audit]** → Intentional, to match the diff and spare build outputs. A runner that
  writes an ignored file it wasn't allowed to is still refused by `checked` and `translated` runners; documented.
- **[`.troupe/` in a theatre run isn't audited]** → troupe writes it during the run, so its changes can't be told
  apart. Tools refuse changes there, Claude Code denies them, and worktree runs never accept them (run-workspaces).
  This is what `unenforced` means on the local stage; #65 closes it.
- **[Claude Code semantics differ by version]** → `Edit` covering `Write` needs 2.1.228; the live test records the
  version, and fixtures are captured from a current Claude Code. A minimum version is left to a follow-up if the live
  test shows a gap.
- **[Shell rules in Claude Code bypass the translation]** → Warned in the run, and the audit catches what they changed.
- **[Audit cost on large theatres]** → Bounded by git's own dirty list; the files adapter walks everything, and is
  for small theatres.
- **[BREAKING config]** → Existing actors with uncovered `expect`, or Claude Code actors with `acceptEdits`, are
  refused with the exact fix. Pre-alpha, no compatibility promise.

## Migration Plan

One pull request, with the protocol change (version 0 changed in place) released as a protocol change by
release-please. An infrastructure pull request adds the `effects` spec's Purpose to `oob/troupe-spec-purposes.json`;
this one merges first. A person's existing actors are fixed with the `troupe config set` each error names.
