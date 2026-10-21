# Design

## Context

See proposal.md for why. The decisions this design builds on are recorded on GitHub, and aren't restated here:
#6 (layout by convention), #7 (JSON Schema as the source), #135 (values are never merged inside), #136 (config
history: one stream per theatre, one `Config.Changed` per command, merged by net change, and the `before`-is-a-hash
comment) and #137 (`--rehearse`).

What exists, from the walking skeleton:

- **The event store** (`contributing/event-store.md`): one segment per session per branch, content-hash event ids
  that leave out lineage, a local notification order, strict reads, all-or-nothing batches, and forks detected and
  refused (`events.stream-forked`) until a settling event names every head. `EventStore.history(stream)` already
  returns both sides of a fork. The text store writes `.troupe/.gitignore` (`local/`) and `.troupe/.gitattributes`
  (`events/** -text`) when they're missing.
- **Runs** (`contributing/runs.md`): `perform` takes the runner, options, instructions and effect check from its
  request (perform-status-logs D4), with the runner's name turned into a command line by `troupe.core.interim`.
  `Run.Started` references the instructions and options as artifacts.
- **The client protocol**: requests, updates and results as JSON Schema in `protocol/schemas/client/`, parsed
  strictly by hand-written types, with the CLI reaching the core only through the dispatcher (an import contract
  checks it).
- **Atomic writes** (`troupe.platform.files`): write a temp file in the same directory, fsync it, rename it over the
  target, fsync the directory on POSIX, and retry with an announced, bounded wait on Windows.
- **Dependencies:** core's only runtime dependency is `eventsourcing`. `jsonschema` is a development dependency
  used by tests.

## Goals / Non-Goals

**Goals:**
- The config event format is the one #136 describes, and is final for format 1: nothing in this change should need
  rewriting history later.
- Every merge of two lines of history gives the same config in every clone, whatever order their events arrive in.
- No config file a person wrote is ever overwritten without `--force`, and `--force` keeps a copy.
- What config holds can be checked end to end: the character set in config is what the runner receives.

**Non-Goals:**
- Reading a file's meaning, in any form (#119).
- Renames (#138). A rename can be added later as a new kind of change entry without touching events already
  recorded, so no stable actor id is minted now.
- A root `troupe.yaml`: the only location setting would be the actor directory, and nothing needs it moved yet. The
  name is reserved (D7).
- Settling forks that have conflicts automatically, or offering a dedicated resolve command. A conflict is resolved
  with `troupe config set`.

## Decisions

### D1. Where things live

| Module or package | Holds |
|---|---|
| `protocol/schemas/config/actor.schema.json` | The actor file kind (D6) |
| `protocol/schemas/events/config-changed.schema.json` | The payload of `Config.Changed` (D2) |
| `protocol/schemas/client/config-*.schema.json`, `flush-*.schema.json` | The config and flush methods (D10) |
| `troupe.core.config.models` | pydantic models generated from the config schemas (D11). Never edited by hand |
| `troupe.core.config.aggregate` | The `Config` aggregate and its `Changed` event (D2) |
| `troupe.core.config.merge` | Working out config from the stream's history, conflicts included (D3, D4) |
| `troupe.core.config.kinds` | The registry of file kinds and reserved names (D7) |
| `troupe.core.config.projection` | Rendering files, the check before replacing one, staging, flush (D8, D9) |
| `troupe.core.config.commands` | `config set`, `config unset`, `config get` and `flush` behind the client protocol |
| `troupe.core.theatre` | The theatre's own files: the patterns `.gitignore` and `.gitattributes` must hold (D12) |
| `troupe.core.interim` | Only the runner table: name to command line and published options schema (D13), until #38 |

The import contract that keeps `troupe.cli` to `troupe.core.client` stays, so the config commands are reachable only
through the protocol, like `perform`.

### D2. The config stream and the `Config.Changed` event

- **One stream per theatre** (#136), with a fixed id: a UUID derived from the name `troupe.config`. Every theatre has
  exactly one config stream, and a store holds one theatre, so a constant can't collide.
- **One topic, `Config.Changed`,** recorded once per command. Its payload:

  ```json
  {"changes": [
     {"path": ["actors", "tester", "runner"], "before": "sha256:41ab…", "after": "claude-code"},
     {"path": ["actors", "tester", "expect"], "after": ["out/hello.txt"]},
     {"path": ["actors", "old"], "before": "sha256:9f2c…"}
   ],
   "files": [
     {"path": "actors/tester.yaml", "hash": "sha256:…"},
     {"path": "actors/old.yaml"}
   ]}
  ```

- **A path is an array of keys**, not a dotted string. The CLI shows and takes dotted paths, but an array can't be
  misread when a runner's option key contains a dot, and needs no escaping rule. Each key is a non-empty string.
- **A value is anything but an object** (#135): a string, number, boolean or array. An object is a group, and a path
  into a group is a path to one of its values. So `after` is never an object.
- **`before` is the hash of the old value** (#136's comment): `sha256:` and the hex SHA-256 of its canonical JSON,
  the same canonical form as event ids (sorted keys, no spaces, UTF-8, no `NaN`). Absent means the value didn't
  exist. **`after` is the new value**; absent means it was removed.
- **Removing a group is one entry addressed to the group,** whose `before` hashes the group's canonical JSON as an
  object, with no `after`. That's how `troupe config unset actors.tester` removes an actor as one intent. It's the one
  place a `before` hashes an object.
- **Setting a group from a file** (`troupe config set actors.tester=@tester.json`) replaces the whole group: the
  command's one event holds an entry for each value that's added, changed or removed under it.
- **`files` lists every file the change wrote or removed,** with the hash of the bytes written, or no hash for a
  removal. It's how flush knows a file is troupe's (D8).
- **An entry whose `before` matches its `after` is never written,** and a command that would change nothing records
  nothing and says so.

Rejected: a dotted path string (needs escaping); `before` as a value, or as a value when small and a hash when large
(two shapes for one field, and a size threshold that would have to be fixed in the event format, since event ids
hash the payload); a `Config.Removed` topic (a missing `after` says it); one event per value, and snapshots (#136).

### D3. Working out config: the merge

Config is read from the stream's whole history (`EventStore.history`), never from `load`, so a fork is merged rather
than refused. With one head, this is ordinary replay. With several:

1. **For each path, find its latest writes:** the entries for that path, or for a group containing it, that no later
   entry for the same path follows in the chain of parents. One latest write gives the value.
2. **For two or more, work out each line's net change since they split.** A latest write's line starts at its
   earliest write to the path that the other latest writes don't descend from. Its net change is from that write's
   `before` to the latest write's `after`, compared by hash.
   - A line whose net change ends where it began hasn't changed the value, and drops out.
   - Lines that changed it to the same value agree.
   - Lines left that changed it to different values are a **conflict**.
3. **Check the merged config as a whole** (D6). An actor that fails is a conflict too, between the changes since
   the split that touched it.
4. **A conflict is between whole changes** (#136): it names each conflicting change in full (its change id, who, when,
   and every entry), not only the path.

A group removed on one line and a value in it changed on another is a conflict: their net changes disagree about
the same path.

The exact formulation of step 2 for criss-cross merges (two branches merged into each other more than once) is
settled by tests, not here. A property test generates histories with branches and merges, delivers their events in
every order, and checks that each clone works out the same config and the same conflicts. A conflict must be reported
exactly when two lines' net changes to a value disagree.

Rejected: a git-style three-way merge from a single base (needs a merge base, which a criss-cross history doesn't
have uniquely); refusing every fork (breaks `perform` after the first merge of two config branches); taking the last
write by local order (the order is local to a clone, so clones would disagree).

### D4. Conflicts block config, and a change resolves them

- **Any conflict blocks every use of config:** `perform`, `flush` and `config set` all refuse with
  `config.conflict`, which lists each conflict with both sides' changes and the fix. `config get` shows the
  conflicts instead of refusing (D10), since a person needs to see them to resolve them.
- **The one exception is a `config set` or `config unset` that resolves every conflict:** a change that sets or
  unsets every conflicting path. It may change other values too, so a person can resolve the window's `min` and `max`
  together. A change that leaves any conflict unresolved is refused, naming what's left.
- **Settling is recorded with the next write** (#136): when `config set` writes to a forked stream, its batch is a
  settling event, whose parents are every head and whose state is the merged config, followed by the change. If two
  clones settle the same fork with the same state, their settling events have the same content id, so the store keeps
  one.
- **Reads create nothing.** A merged, unsettled config is worked out every time it's read.

### D5. The event store merges a fork through its aggregate

Today loading a forked stream is always refused. This change lets a stream's aggregate own its forks: a stream whose
aggregate defines a merge is read through the merge, and appending to it is allowed when the batch starts with a
settling event. Config is the only such aggregate. Runs keep the current rule: a run stream is written by one
`perform` in one clone, so a forked run is a fault. `contributing/event-store.md` already reserved this for config.

### D6. The actor kind

`actors/<name>.yaml` and `actors/<name>.md` are the actor `<name>` (#6). The name follows the client protocol's actor
pattern (`[a-z][a-z0-9-]{0,63}`).

| Field | In | Required | What it is |
|---|---|---|---|
| `runner` | `.yaml` | yes | The runner's name, from the runner table (D13) |
| `options` | `.yaml` | no (default `{}`) | The runner's options, checked against that runner's published options schema |
| `expect` | `.yaml` | yes | The effect check: theatre-relative paths the run must create or change. `[]` means no check, and has to be written, as `--no-effect-check` had to be |
| `character` | `.md` | no | The actor's standing prompt, as text. The whole file is the value |

- **The schema describes the YAML file:** closed, every field typed, titles and descriptions on every field for
  editors and later forms, `$schema` allowed as a key. The `.md` file has no schema: its whole content is one string
  value.
- **The merged actor is checked whole** (D3, step 3): against the schema, and its `options` against its runner's
  options schema with `jsonschema` at runtime. A plugin's schema can't be generated into core's types, so this is
  the one place core validates with a JSON Schema library directly.
- **The same check runs before each change is recorded,** so an invalid change is refused, naming the path and the
  rule, and nothing is recorded.

Rejected: an effect check with a `none` form beside its list (two shapes for one value, which #135 would have to
compare across a merge); a `character` reference field in the YAML (#6's typed references, such as
`file:tester.md`, matter once a file can point elsewhere; in this change the character is always the actor's own
`.md`, and #119 or a later change adds the field when references can be set).

### D7. The registry of file kinds, and reserved names

A table in `troupe.core.config.kinds` maps path patterns under `.troupe/` to kinds:

| Pattern | Kind |
|---|---|
| `actors/<name>.yaml` | actor (its schema) |
| `actors/<name>.md` | the actor's character (text) |
| `events/`, `local/`, `.gitignore`, `.gitattributes`, `troupe.yaml` | reserved: never config. `troupe.yaml` is held for #6's root file |
| `.<file>.troupe~` beside a config file | a staged write (D9) |
| `.DS_Store`, `Thumbs.db`, `desktop.ini` | operating-system files, ignored, in one named list |

Any other file in a config directory (`actors/`) is refused when flushing, naming it (`config.unknown-file`). The
table's entries have the shape a guest's later registration will need (pattern, kind, schema), but guests can't add
to it yet.

### D8. Is a file safe to replace?

Before writing a file, flush asks whether replacing it could lose anything that exists only in that file. It's safe
when the file's bytes hash to:

- **what troupe would write now** from config (nothing to do);
- **a hash troupe recorded for that path:** in any `Config.Changed`'s `files` on any line of history, or in this
  clone's own record of files flush wrote (`.troupe/local/config/written.jsonl`, append-only, a torn last line
  trimmed). The local record covers files flush wrote again with no event, for example after a troupe upgrade
  renders a file differently;
- **or there's no file.** In this change files are only for looking at, so a deleted file is written again, with a
  notice. Once #119 reads files back, a deletion is a removal instead.

Anything else is refused with `config.file-not-troupes`, naming the file and the fix: undo the edit (`git restore`),
or `troupe flush --force`. `--force` stores the file's bytes in the artifact store first, and names each file and
the hash of what it kept.

Rejected: timestamps (git sets a file's time to the checkout's; a deleted file has none); reading the file to see what
changed (#119); overwriting silently.

### D9. Writing files: stage, record, replace

A config write runs in this order, holding the projection lock (`.troupe/local/config/.lock`) throughout, so flushes
and config writes in two terminals queue:

1. Check every file it will touch is safe to replace (D8). If not, refuse, and write nothing.
2. Write each new file whole, fsynced, beside its target as `.<file>.troupe~` (for example `.tester.yaml.troupe~`).
3. Record the `Config.Changed`, whose `files` holds each staged file's hash.
4. Rename each staged file over its target, with the platform seam's atomic replace, and remove each file the change
   removed.

On the next flush, a staged file whose hash an event names is that event's unfinished write: it's moved into place.
One no event names was staged before a crash that came before step 3: it's removed. Staging in the target's own
directory keeps the rename on one filesystem, which is what makes it atomic.

In this change, recovery would also work without staging, since a missing or older file is safe to write again (D8).
Staging is here so that #119 inherits an order where a crash between steps 3 and 4 is never mistaken for a hand edit.

**Rendering.** YAML is written with ruamel.yaml, block style, keys in the schema's order, and two lines first: the
`# yaml-language-server: $schema=…` comment and the `$schema:` key, both naming the same relative path to
`.troupe/local/schemas/` (#7, and both forms, as agreed). The character file is the text exactly, UTF-8, with the line
endings it was given. The file's hash is the SHA-256 of the bytes written.

### D10. Commands, methods and the CLI

| CLI | Method | What it does |
|---|---|---|
| `troupe config set <path>=<value>…` | `config.set` | Records one change setting each value (D2). `<path>=@<file>` reads the value from a file |
| `troupe config unset <path>…` | `config.set` (unset entries) | Records one change removing each value or group |
| `troupe config get [<path>]` | `config.get` (a query) | Shows the merged config, or the value or group at a path, with notices |
| `troupe flush [--force]` | `flush` | Makes the files exactly what config says (D8, D9) |
| `troupe perform <actor> [--direction <text>]` | `perform` | Runs the actor from config |

Every command that changes anything takes `--rehearse` (#137), and `config.set`, `flush` and `perform` take
`rehearse` in their requests.

- **Every command that uses config flushes first,** so the files are right before anything reads config, and a
  refused file stops the command before it does anything.
- **Values typed by the schema.** The CLI looks up the type at the path: a string takes the text as given; an
  integer, number or boolean is parsed strictly (`true`, not `yes`); an array is JSON. Where the schema doesn't give
  one type (a runner's option that's `oneOf` several), the value must be JSON, given with `--json`. The core's request
  carries JSON values, so typing is the CLI's job, and a later surface sends JSON directly. With `@<file>`, a string
  value is the file's text, and anything else is the file parsed as JSON or YAML by its extension.
- **`config get` shows conflicts** instead of refusing, since a person needs to see them to resolve them.
- **A change carries an optional `--reason`,** recorded in lineage.

### D11. Types generated with pydantic

- **datamodel-code-generator** turns `protocol/schemas/config/` and `events/config-changed.schema.json` into
  pydantic v2 models in `troupe.core.config.models`: strict, `extra="forbid"`, frozen. The generated file says it's
  generated and how to regenerate it.
- **`scripts/generate_models.py`** writes the file, and its `--check` mode fails when the file isn't what the
  schemas generate. `scripts/check.py` runs the check, so a schema can't change without its types.
- **A differential test** checks that each model accepts exactly what `jsonschema` accepts for its schema, on inputs
  generated from the schema and on near misses: unknown keys, wrong types, values outside a pattern.
- **The pydantic mypy plugin** keeps `mypy --strict` meaningful over the models.
- The hand-written runner and client types aren't moved in this change. The config method messages are written
  like today's client types, so the client protocol has one style until a later change moves it all.

### D12. The theatre's own files

`troupe.core.theatre` holds the patterns `.troupe/.gitignore` and `.troupe/.gitattributes` must contain:

| File | Patterns |
|---|---|
| `.gitignore` | `local/`, `.*.troupe~` |
| `.gitattributes` | `events/** -text`, `actors/** -text` |

Whenever troupe writes into `.troupe/`, it appends any missing pattern under a comment saying troupe added it and
why. It never changes, moves or removes a line that's there. The text store calls this instead of writing its own
constants. `actors/** -text` matters on Windows, where `core.autocrlf` would otherwise turn a config file's line
endings into CRLF on checkout, so its hash would never match what troupe wrote.

A person who deletes one of troupe's lines gets it back on the next write. The docs say so.

### D13. Runners: the interim table gains each runner's options schema

Config checks options against the runner's published options schema when a change is recorded, without starting the
runner. So each entry in `troupe.core.interim.RUNNERS` names the command line and where the runner's options schema
is. For the scripted runner, that's its `schemas/` shipped as package data, found through the installed distribution.
#38 replaces the table with plugins named and pinned in config.

### D14. `perform` from config, and what a run records

- **The request is `{actor, direction?, rehearse?}`.** The runner, options, effect check and character come from
  the merged config. An actor that isn't in config is `config.unknown-actor`, naming the actors there are.
- **`run/start` carries `direction` and, when the actor has one, `character`** (the runner-contract delta). The
  contract stays version 0, the draft.
- **`Run.Started` records `config`:** the sorted ids of the config stream's heads that the merged config was worked
  out from. With one head, that's one id. The run's direction is stored as an artifact and referenced, as
  instructions were. The options' artifact reference is dropped: the config version says what they were, in one
  place.
- **`perform --rehearse`** runs every check up to starting the runner: identity, policy, the stage's admission and
  the actor's config. It reports what it would run (actor, runner, stage, effect check, and the character and
  direction by hash and length), and starts nothing.

### D15. Rehearsals and their exit code

A rehearsal runs the command's checks and returns a plan instead of acting: the change it would record, the files it
would write, stage or refuse, or the run it would start. It records nothing and writes nothing. A new exit code,
`WOULD_CHANGE` (3), means it would succeed and change something; 0 means it would succeed with nothing to do. A
refusal exits with its own code. So `troupe flush --rehearse` in CI fails a branch whose files aren't what its events
say. `perform --rehearse` exits 3 whenever it would run, as #137's rule says.

### D16. Character and direction

The words go everywhere at once: the runner contract (`direction`, and `character`), the client protocol's `perform`
request, `Run.Started`'s payload, the CLI flag (`--direction`), the user docs and the glossary. The scripted runner
gains a step that checks the character it received by hash, and fails the run if it doesn't match, so a test proves
the character went from config to the runner.

## Risks / Trade-offs

- [The merge rule is the subtlest code in the change, and its mistakes would be in git for ever.] → The property test
  in D3 runs across branches, merges and delivery orders. Every bug found becomes a fixed example.
- [Generated pydantic models and JSON Schema disagree on an edge, such as a regex dialect.] → D11's differential test,
  and strict schemas keep to a subset both handle.
- [Canonical JSON of a float isn't the same in every language.] → Only Python reads and writes config today. Floats
  in config are rare (none in the actor kind). A later surface in another language must match Python's shortest
  round-trip form, and a test pins it with examples.
- [A ruamel.yaml upgrade renders a file differently.] → The local record of what flush wrote (D8) keeps such files
  troupe's, and ruamel.yaml is pinned to a minor version.
- [Replaying the whole config stream on every command gets slow.] → Config is small and changes rarely. The house
  (#63) brings long-lived projections.
- [A theatre cloned before its `.gitattributes` held `actors/** -text`, on Windows with `core.autocrlf`.] → The
  pattern lands with the first config write, before any config file is committed. A clone that still has CRLF files
  sees them refused, and the message says to `git add --renormalize .troupe`.
- [`--force` stores what it replaces in `.troupe/local/`, which isn't in git.] → It's a safety copy for this clone,
  and the message says where it is.

## Migration Plan

Pre-alpha, with nothing released, so there's no migration path for users. Theatres made while developing the
skeleton hold `Run.Started` events with `instructions` and `options`, which strict reads refuse once the payload
schema changes. Delete their `.troupe/events/`. The CLI's `--runner`, `--runner-options`, `--expect`,
`--no-effect-check` and `--instructions` flags are removed, so the user docs' first-performance page changes with
this change.
