# Tasks

## 1. Dependencies and the type generator (design D11)

- [x] 1.1 Add `pydantic`, `jsonschema` and `ruamel.yaml` to the `troupe` package's runtime dependencies (ruamel.yaml
  pinned to a minor version), and `datamodel-code-generator` to the dev group. Enable the pydantic mypy plugin. Verify
  `uv sync` succeeds and `uv run scripts/check.py` passes unchanged
- [x] 1.2 Add `scripts/generate_models.py`, which generates `troupe.core.config.models` from `protocol/schemas/config/`
  and `protocol/schemas/events/config-changed.schema.json` as strict, frozen pydantic v2 models with
  `extra="forbid"` and a "generated, don't edit" header, and whose `--check` mode fails, naming the file and the
  regenerate command, when the file differs. Run `--check` from `scripts/check.py` and declare it in
  `scripts/check-paths.toml`. Verify that changing a schema without regenerating fails the check
  - Done as the repository already does for `docs_reference.py --check`: a test
    (`test_the_models_are_what_the_schemas_generate`) runs `--check`, and `scripts/check.py` runs the tests. Nothing
    is declared in `check-paths.toml`: an unlisted script runs the full check, which is right for one whose output
    is core code. `test_a_schema_changed_without_its_models_fails_the_check_naming_the_fix` adds a field to a copy of
    the actor schema and sees `--check` fail, naming the file and the command.
  - The generator is given one bundled schema (design D11): cross-file references copied in, the runner options
    extension point typed as a JSON object (checked against the runner's own schema at runtime, D6), and the event
    store's `lineage` and `timestamp` left out. The models' base class (`troupe.core.config.base.StrictModel`)
    validates strictly with Python's regex engine, as `jsonschema` does, and refuses a field given as null.

## 2. The schemas (design D2, D6)

- [x] 2.1 Write `protocol/schemas/config/actor.schema.json` (D6): `$schema`, `runner`, `options` as the runner
  extension point, `expect`, every field with a title and description. Verify the protocol strictness test passes
  over it, and that an unknown key, a missing `expect` and an absolute `expect` path each fail validation
- [x] 2.2 Write `protocol/schemas/events/config-changed.schema.json` (D2) and register the `Config.Changed` topic in
  the event-record schema's topic table. Verify the event-payload tests accept a recorded change and refuse a null
  `before`, an object `after`, and a path with an empty key
  - Checked against a hand-built record here (`test_a_config_change_record_validates_by_its_topic`, and ten
    refusals); task 5.2 adds a test over the lines a real `config set` writes. The settling event's topic moved to
    6.3, where its payload's shape (the merged config) is decided.
- [x] 2.3 Generate the models and add the differential test: for each config schema, inputs generated from it and
  near misses (unknown keys, wrong types, values outside a pattern) are accepted or refused alike by the model and
  by `jsonschema`. Verify the test passes, and fails when a model is hand-edited to accept an unknown key (revert
  before commit)
  - The differential test found two real disagreements before it passed, both fixed in the generator's inputs or
    the base class, and both kept as fixed `@example`s: an object with a null inside a list value (the generator
    typed nested objects as `dict[str, Any]`), and an optional field given as null. 5,000 examples per test then
    agreed. With `Actor` hand-edited to `extra="allow"`, both the up-to-date check and the differential test failed.

## 3. The theatre's own files (design D12)

- [x] 3.1 Add `troupe.core.theatre`'s required patterns (`.gitignore`: `local/`, `.*.troupe~`; `.gitattributes`:
  `events/** -text`, `actors/** -text`) and the append-only rule: a missing pattern is appended under troupe's
  comment, and no existing line is changed, moved or removed. Make the text store use it instead of its own
  constants. Verify with tests for a missing file, a file holding a person's own lines (unchanged and in place), and
  a file missing one pattern, and that the event-store tests still pass
- [x] 3.2 Update `contributing/event-store.md`'s layout and `docs/the-company/theatres.md`'s file tree, including that
  a deleted troupe line comes back on the next write. Verify the docs tests pass

## 4. The event store merges a fork through its aggregate (design D5)

- [x] 4.1 Let a stream's aggregate declare that it merges its own forks: such a stream is read through the merge
  instead of refused, and a batch may record a settling event followed by ordinary events. Run streams keep the
  current rule. Verify with tests for each scenario in the event-store delta, including two clones settling the
  same fork to one event id, and that every existing fork test still passes
  - The store already allowed most of it: `history` returns both sides of a fork, and a batch whose first event
    settles gives the events after it that event as their parent. What changed: `Command.record` takes
    `settles=`. An aggregate "declares" that it merges its forks by reading `history` instead of `load`; there's no
    flag to set. Tests: `test_forks.py` (history read whole, one batch settling and changing, all or nothing, two
    clones settling to one event).
  - `history` stays the store's lenient listing: refusing a missing parent there broke the ordering state machine,
    which reads it as "every visible event" while it deletes segments, and the run queries read it too. So the
    config merge checks parents itself (task 6.1), refusing with `events.missing-parent` as `load` would.
- [x] 4.2 Update `contributing/event-store.md`'s "Forks and settling" section to say which aggregates merge their
  forks and that settling may share a batch. Verify the event-store doc test passes

## 5. The config aggregate and its changes (design D2, D6, D13)

- [x] 5.1 Ship the scripted runner's `schemas/` with its installed package, and give each `troupe.core.interim.RUNNERS`
  entry the location of its options schema (D13). Verify a test reads the scripted runner's options schema from the
  installed plugin without starting it
  - The schemas moved to `plugins/runner-scripted/src/troupe_runner_scripted/schemas/` (installed with the
    plugin; references in tests, `check-paths.toml`, the plugin's README and `contributing/runners.md` updated).
    `test_a_runners_options_schema_is_read_from_the_installed_runner_without_importing_it` runs a fresh interpreter
    and checks the runner's package was never imported. The built plugin wheel holds both schemas.
- [x] 5.1a Add `scripts/package_schemas.py`, which copies `protocol/schemas/` into `packages/troupe/src/troupe/protocol/`
  with a `--check` mode, a test that runs the check, and `troupe.core.schemas`, the one place core finds a schema by
  its `$id` (D17). Verify the test fails when a source schema changes without the copy, that a built wheel holds the
  copy, and that a scripted runner's options are validated through `troupe.core.schemas` against its installed schema
  - `test_schemas.py`: the copy check passes; a changed source schema and a stray copy each fail it, naming the file
    and the command; every protocol schema is found by its `$id` from the copy; options are checked against the
    runner's schema and the contract schemas it refers to. A wheel built with `uv build --package troupe` holds all
    28 schemas, and installed with the runner's wheel into a fresh environment outside the checkout, it validated
    the scripted runner's options (and refused an unknown key) without importing the runner (2026-10-21).
- [x] 5.2 Add `troupe.core.config.aggregate`: the config stream's fixed id, `Config.Changed` with array paths, `before`
  as the canonical-JSON hash and `after` as the value, group removal as one entry, setting a group from data, and no
  event when nothing changes. Verify with tests for each scenario under "A command records one change", "A change
  entry holds…", "Objects are groups…", "A group is removed as one entry" and "A group can be set whole from a
  file", including a test that a `before` equals the hash of the earlier `after` for strings, numbers, booleans and
  arrays
  - `troupe.core.config.changes` builds entries (`set_value`, `unset`, and `change` for one command's net change
    across several values) and applies them; `aggregate.changed` builds the event. `test_config_changes.py` (17
    tests, one a hypothesis property over every kind of value) records real events and validates every line the
    store wrote against the event-record schema, the real-recording check task 2.2 deferred here.
- [x] 5.3 Check every change before it's recorded (D6): the merged actor against its schema, its options against its
  runner's schema with `jsonschema`, and the actor name pattern, refusing with the path and the rule. Catalogue every
  new error code with its details schema. Verify with tests for a misspelt field, an unknown option, a missing
  `expect`, a path outside the theatre and a bad actor name, each recording nothing
  - `troupe.core.config.kinds.check` refuses with `config.invalid` (catalogued), naming the path and the rule in
    words taken from the schemas' descriptions; `test_config_kinds.py` (13 tests) covers each case above and more
    (a runner set to a group, an unknown runner, an unknown kind, `$schema` set by hand). "Recording nothing" is a
    property of the command that checks before recording, so it's verified with the commands, in 8.2.

## 6. Merging and conflicts (design D3, D4)

- [x] 6.1 Add `troupe.core.config.merge`: config worked out from the stream's whole history, each line's net change
  per path since the split, agreement, a change and a change back, and group removal against a change inside the
  group. Refuse an event whose parent isn't here with `events.missing-parent`, naming its file, as `load` does. Verify with tests for each scenario under "A merge combines each line's net change" and "Differing net
  changes…", with branches made in a real git repository (the existing test helpers)
- [x] 6.2 Add conflicts from validation (a merged actor that fails its schema or its runner's options), conflicts
  reported as whole changes, the block on every config use except `config get`, and the resolution rule (a change
  must set or unset every conflicting path). Verify with tests for the window example, the runner-and-options
  example, `perform` refused by a conflict on another actor, and a change that resolves nothing being refused
- [x] 6.3 Record settling with the next write: one batch, a settling event naming every head with the merged config,
  then the change. Write the settling event's payload schema (the merged config) and register its topic in the
  event-record schema's topic table. Reads record nothing. Verify with tests for a read after a merge (nothing recorded) and the first
  write after it (one head after)
- [x] 6.4 Add the property test (D3): generated histories with branches, merges (criss-cross included) and changes and
  changes back, delivered in every order to separate clones, check that every clone works out the same config and
  conflicts, and that a conflict is reported exactly when two lines' net changes to a value differ. Use the project's
  hypothesis profiles. Verify it passes, and that it fails when the net-change rule is temporarily replaced by "latest
  writes differ" (revert before commit)
  - Group 6 as built: `troupe.core.config.merge` (points, latest covering writes, each line's net change, replay
    leaving out lines that dropped out and both sides of a conflict; settling events read as joins), and
    `troupe.core.config.stream` (`read`, `refuse_conflicts`, and `record`, which checks, refuses an unresolved
    conflict, and settles a fork in the change's batch). `config.conflict` is catalogued, and the settling event has
    its own class (`Config.Settled`), payload schema (`events/config-settled.schema.json`) and topic in the
    event-record table, so the store's tests can still settle a test aggregate under the generic `Settled` topic.
  - `test_config_merge.py` (13 tests, on real git branches): the scenarios in 6.1 to 6.3, both merge directions,
    the window conflicting whole, a group removed against a change inside it, options that stop suiting a second
    runner (a fake `modelled` runner with its own options schema), the block naming the conflict, a read recording
    nothing, a resolution recording who, a change that resolves nothing refused with nothing recorded, and the
    first write after a merge settling in one batch with every line valid by its schema.
  - `test_config_merge_properties.py`: generated histories with forks, changes back, settles and criss-cross
    merges, delivered in other valid orders, give the same config, conflicts and heads; and an oracle that replays
    each branch alone agrees on exactly which paths conflict and on every merged value. 150 and 200 examples in the
    suite; a one-off run of 5,000 each passed (2026-10-22). With the net-change rule replaced by "latest writes
    differ", the oracle test failed at once; restored.
  - A validation conflict is reported only for an actor with no conflict already, since resolving that changes its
    values (design D3).

## 7. Files: the registry, flush and the check before replacing (design D7, D8, D9)

- [x] 7.1 Add `troupe.core.config.kinds` (D7): the actor's `.yaml` and `.md`, the reserved names, staged writes and the
  named operating-system files. Verify with tests that a stray file in `actors/` is `config.unknown-file` and
  `.DS_Store` is ignored
- [x] 7.2 Render files (D9): YAML with ruamel.yaml, block style, keys in schema order, the language-server comment and
  the `$schema` key first, both naming `https://troupe.run/protocol/0/config/actor.schema.json`, and the character's
  text exactly. Verify a written actor file validates against the actor schema troupe carries
- [x] 7.3 Add the check before replacing (D8): what config would write now, any hash in a change's `files`, the local
  written record (`.troupe/local/config/written.jsonl`, a torn last line trimmed), or no file. Anything else is
  `config.file-not-troupes`. Verify with tests for a hand edit (refused, nothing recorded), a file restored from an
  earlier commit, a deleted file and a clean git merge of two branches' files
- [x] 7.4 Add staged writes and recovery (D9) under the projection lock: stage `.<file>.troupe~`, record, replace with
  the platform seam's atomic replace; on the next flush, move a staged file an event names, and remove one no event
  names. Verify with tests that stop after recording and before recording (by injecting a failure), and a test that
  two config commands in two processes queue, with the wait announced
- [x] 7.5 Add `flush` in the core, run first by every command that uses config, and `--force`, which stores each
  replaced file's bytes in the artifact store and names its hash. Verify with tests for each scenario under "Flush
  makes the files what config says" and "Force replaces a file and keeps a copy"
  - Group 7 as built: the registry in `troupe.core.config.kinds`; `troupe.core.config.projection` (rendering, the
    check before replacing, staged writes and their recovery, this clone's record of files flush wrote, the lock
    with an announced wait, `flush` and `execute`). New codes: `config.unknown-file`, `config.file-not-troupes`,
    `config.local-malformed`, and the notice `config.file-rewritten`.
  - `test_config_files.py` (23 tests). Its YAML round-trip property (every file reads back the same under YAML 1.2
    and YAML 1.1, as PyYAML and many editors read it) found two real bugs on its first runs, both fixed and pinned
    as examples: a string holding NEL (U+0085, a line break to YAML 1.1) written raw, and a float such as `1e-05`
    written without the dot a YAML 1.1 float needs. A one-off run of 6,000 examples then passed (2026-10-22). The
    queueing test holds the lock in a child process and checks the flush waited and announced it.
  - "Perform flushes first" (a scenario under "Flush makes the files what config says") is checked with perform,
    in 10.3.
- [ ] 7.6 Add a test on Windows CI that a config file committed and checked out again with `core.autocrlf=true` keeps
  troupe's line endings and isn't refused. Verify it runs (not skipped) on the Windows runners
  - Written (`test_a_config_file_checked_out_with_autocrlf_keeps_troupes_line_endings`, with a control that removes
    the attribute and sees the file turn CRLF and be refused). `core.autocrlf` converts on any OS, so it runs on all
    three, and passes on macOS. Ticked once CI shows it passing on the Windows runners (11.3).

## 8. Commands, the client protocol and the CLI (design D10)

- [ ] 8.1 Write the client-protocol schemas for `config.set` (set and unset entries, `reason`, `rehearse`),
  `config.get` and `flush` (`force`, `rehearse`), and their hand-written message types in today's style. Verify the
  client-protocol schema tests cover them, including the random round trip
- [ ] 8.2 Add the core commands behind the dispatcher, each flushing first and holding the projection lock while
  writing. Verify a dispatcher test for each method, that a refused change (from 5.3's cases) records nothing and
  writes no file, and that the import contract keeping `troupe.cli` to
  `troupe.core.client` still passes
- [ ] 8.3 Add `troupe config set`, `troupe config unset`, `troupe config get [--json]` and `troupe flush [--force]`,
  with values typed by the schema at their path, `@<file>`, `--json` for values with no single type, and `--reason`.
  Verify with CLI tests for each scenario under "Config commands" and "Command-line values are typed by the schema"
- [ ] 8.4 Write `docs/stagecraft/hand-edit-config.md` and `docs/the-company/theatres.md`'s config section as built:
  files are written by troupe and checked before replacing, flush and `--force`, conflicts and how to resolve them.
  Generate the config section of `docs/prompt-book/config-schema.md` from `protocol/schemas/config/` with
  `scripts/docs_reference.py`, and regenerate the CLI reference. Verify the docs tests pass, including vocabulary and
  links

## 9. Rehearsals (design D15)

- [ ] 9.1 Add `WOULD_CHANGE = 3` to `troupe.core.exit_codes` with its docstring, and `--rehearse` for `config set`,
  `config unset` and `flush`, each returning its plan and recording and writing nothing. Verify with tests for each
  scenario under "Every command that changes anything can be rehearsed" and "A rehearsal's exit code says what it
  found", and that the generated exit-code table in `docs/prompt-book/cli.md` lists the new code

## 10. Perform from config, character and direction (design D14, D16)

- [ ] 10.1 Rename `instructions` to `direction` and add an optional `character` in the runner contract's `run/start`
  schema, the runner types and the run host. Add a conformance case that a runner receives both unchanged and never a
  null character. Verify the runner-protocol schema tests and the conformance suite pass against the scripted runner
- [ ] 10.2 Add the scripted runner's character-check step to its options schema and runner. Verify with its tests for
  a matching hash, a different one and a missing character, and that every shipped script still validates
- [ ] 10.3 Change `perform`'s request to `{actor, direction?, rehearse?}`, take the runner, options, effect check and
  character from the merged config, record `config` (the sorted head ids) and the direction's artifact in
  `Run.Started` (dropping `instructions` and `options`), and refuse an unknown actor with `config.unknown-actor`.
  Update `run-started.schema.json`. Verify with tests for each scenario under "A run uses the actor as config defines
  it" and "What a run was asked to do is kept", including a run whose script checks the character it received
- [ ] 10.4 Remove `--runner`, `--runner-options`, `--expect`, `--no-effect-check` and `--instructions` from the CLI, add
  `--direction` and `--rehearse` to `perform`, and shrink `troupe.core.interim` to the runner table. Verify with CLI
  tests for each scenario under "Perform names an actor from config", and the rehearsal scenario for `perform`
- [ ] 10.5 Add character and direction to the glossary, and widen rehearsal's meaning to every command's dry run (#137).
  Update `contributing/runs.md` and `contributing/runners.md`. Rewrite `docs/opening-night/first-performance.md` and
  `first-theatre.md` for config. Verify the docs tests pass, including that the CLI page's examples run as written

## 11. Integration

- [ ] 11.1 In a fresh scratch theatre, follow `docs/opening-night/first-performance.md` as written: define the actor
  with `troupe config set`, `troupe perform` it with a direction, read it back with `troupe status` and `troupe logs`,
  and check that the run's start names the config version and that the files under `.troupe/actors/` are what config
  says (`troupe flush --rehearse` exits 0). Record the transcript in this task
- [ ] 11.2 In a scratch git repository, make config changes on two branches (one to each of two actors, then one to the
  same value), merge them, and check `troupe config get` shows the merged config, then the conflict, and that a
  resolving `troupe config set` settles it. Record the transcript in this task
- [ ] 11.3 Run `uv run scripts/check.py` and verify it passes. Open the PR with `Closes #60`, and verify every CI job
  passes on Linux, macOS and Windows, including 7.6's Windows test

## Workflow follow-up

- Run `/opsx:archive` on the branch before merging, so the PR lands code, tests and specs together.
- After the merge, comment on #60 with the PR and the archived change, check it's closed, and check its card on the
  troupe roadmap board says Done. Check #135, #136 and #137 still say Done.
