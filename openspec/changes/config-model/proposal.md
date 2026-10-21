# Proposal

Issue: troupe-run/troupe#60. Builds on the walking skeleton (#33). Implements decisions #6 (layout), #7 (JSON Schema
as the source), #135 (values are never merged inside), #136 (config history) and #137 (`--rehearse`), all agreed with
the owner, the last three in the `/opsx:explore` session on #60 on 2026-10-21. Renames (#138) and reading hand edits
back (#119) come after it.

## Why

`troupe perform` defines its actor from scratch on every run: `--runner scripted --runner-options hello.json --expect
out/hello.txt`. Nothing about an actor is kept, so nothing can be reviewed, shared through git or built on: not
roles, not gates, not a second runner. Config is the first capability after the skeleton because its rules are
largely decided, and every later slice plugs into it.

It's also where troupe's event sourcing meets git branches for the first time. Config events are committed, so two
lines of history can each change config and later be merged. What a config event says, and how a merge reads two
branches' events, is fixed by the first event recorded and stays in git for ever. So it has to be right now (#136).

## What Changes

- **Config is events.** `troupe config set` records one `Config.Changed` event per command, with lineage, through
  the client protocol. For each value it changes, the event holds the value's logical path as an array of keys
  (`["actors", "tester", "runner"]`, written `actors.tester.runner` on the command line), the hash of its old value
  (`before`) and the new value (`after`). A removal has no `after`. troupe reads config
  only from these events, in one stream per theatre (#136).
- **Branch merges are read, never refused outright.** When two lines of history have both changed config, troupe
  works out each line's net change since they split and combines them. Two lines that set one value to different
  things, or whose combined config fails validation, are in conflict as whole changes. Any conflict blocks config
  until a change resolves it. Values are never merged inside (#135).
- **The actor is the first kind of config:** its runner, the runner's options, its effect check and its
  **character** (its standing prompt). `actors/tester.yaml` and `actors/tester.md` are the actor `tester` (#6). Each
  file kind has a strict JSON Schema in `protocol/` (#7, #70), named in the file by both a `$schema:` key and a YAML
  language-server comment, and copied to `.troupe/local/schemas/` for editors.
- **Files are a one-way projection.** `troupe flush` writes each config file whole from config, and every command
  that uses config flushes first. troupe never reads a file's meaning in this change. Before replacing a file it
  checks the file is one troupe wrote, by hash, and refuses one that isn't, naming the file and the fix. `--force`
  replaces it anyway, keeping a copy of what it replaced. A whole file is staged beside its target and moved into
  place with one atomic replace, so a crash part-way is recovered from what the events vouch for.
- **`perform` takes its actor from config.** **BREAKING:** `--runner`, `--runner-options`, `--expect` and
  `--no-effect-check` are removed, with no overrides. `--instructions` becomes `--direction`. The run's start
  records the config version it ran with.
- **Vocabulary: character and direction.** An actor's standing prompt is its **character**; what a run is asked to
  do is its **direction**. **BREAKING:** renamed everywhere: the runner contract's `run/start` (`instructions`
  becomes `direction`, and an optional `character` is added), the client protocol, the run's start and the CLI.
- **`--rehearse` on every command that changes anything** (#137): `troupe config set`, `troupe config unset`,
  `troupe flush` and `troupe perform`. A rehearsal changes nothing and reports what the command would do, with an
  exit code that says whether it found work to do. `perform --rehearse` runs every check and starts nothing.
- **Schema-first types.** Python types for config are generated from the JSON Schemas as pydantic models, and a check
  fails when a schema changes without its types.

## Capabilities

### New Capabilities
- `config`: config as events: the `Config.Changed` event, logical paths and values, the config stream and its merge
  across branches, conflicts and their resolution, the actor kind and its schema, and the `troupe config` commands.
- `config-files`: config's projection to files under `.troupe/`: the registry of file kinds and reserved names,
  `$schema` in files, flushing, the check before a file is replaced, staged writes and crash recovery, and
  `troupe flush`.

### Modified Capabilities
- `cli`: `perform` names an actor from config and takes `--direction`; the interim flags are removed; `--rehearse`
  and its exit code; the `config` and `flush` commands.
- `runs`: a run's start records the config version and the direction, and takes the runner, options, effect check
  and character from config.
- `runner-protocol`: `run/start` carries `direction` (renamed from `instructions`) and an optional `character`.
- `scripted-runner`: a step that checks the character it received, so a test can prove it arrived.
- `client-protocol`: the config and flush methods; `perform`'s request names the actor and direction only.
- `event-store`: a stream's aggregate may merge its own forks when it's read (config does); settling is recorded
  with the next write.

## Impact

- New: `protocol/schemas/config/` (the actor file kind), `protocol/schemas/events/config-changed.schema.json`,
  client-protocol schemas for the config and flush methods, `troupe.core.config` (the aggregate, the merge, the
  projection, the file-kind registry and flush), generated pydantic models, and their up-to-date check.
- Changed: `troupe.core.runs.perform`, `troupe.core.interim` (only the runner table remains, until #38),
  `protocol/schemas/runner/run-start.schema.json`, `plugins/runner-scripted`, the client protocol's `perform`
  messages, `troupe.cli`, `troupe.core.exit_codes`, the text store's `.gitignore` handling, and the user and
  contributor docs that say config isn't built yet.
- Dependencies, new at runtime: pydantic, jsonschema (to check runner options against a plugin's schema) and
  ruamel.yaml (to write YAML). datamodel-code-generator, for development only.
- Out of scope: reading hand edits back and `troupe sync` (#119); renames and `troupe config mv` (#138); a root
  `troupe.yaml` (no location setting needs it yet); policy files (#71); roles and people (#61); a setup command
  (still undecided); rehearsals that run stub actors (#137, later); publishing schemas at a URL; moving the
  hand-written runner and client types onto the generator.
