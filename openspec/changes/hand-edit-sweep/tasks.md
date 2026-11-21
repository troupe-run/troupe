# Tasks

The orchestrator sequences full checks (`uv run scripts/check.py`): ask before each one, and check `uptime` first.
Each group lands its own tests and docs. Write each new test so it fails on main (or before its group's code) and
say so in the tick. Commit by group, so the review can be split by slice (design, Risks).

## 1. Reading a file's values (design D2)

- [x] 1.1 In `core/config/kinds.py` (or a new `core/config/reading.py`), read a config file into the part of config
      it owns: an actor `.yaml` (every field but `character`), an actor `.md` (the character, exact UTF-8 bytes), and
      a runtime `.yaml`. YAML 1.2 safe load. Verify with tests over real rendered files: reading what `render()`
      writes gives back exactly the config it was rendered from, for every field `FIELD_ORDER` and
      `RUNTIME_FIELD_ORDER` name (a property test over generated actors and runtimes).
      Done: `core/config/reading.py`; property tests over generated actors and runtimes round-trip `render()` (new module, so they fail on main).
- [x] 1.2 Refuse invalid files as `config.file-invalid`, with the rule in details and the value never repeated:
      syntax error (line and column), duplicate key, anchor, alias, tag or merge key, a non-mapping top level, a
      null, non-UTF-8 `.md`, `$schema` naming another kind, and a file with no values (rule `empty`, design D4).
      Verify with a test per rule, each checking the code, the file in the message, the rule, and that a canary value
      isn't in the message. Add `config.file-invalid` to `core/errors.py` and `protocol/schemas/error.schema.json`
      (and the package copy).
      Done: 18 parametrised rules plus empty-file fixes, line/column and absolute path; codes in errors and the error schema (`write-back-failed` lands with group 3, since protocol_guard needs a raiser).
- [x] 1.3 Run the values through `config set`'s checks (kind schema, runner options schema) and report failures as
      `config.file-invalid` naming the file and the path. Verify with tests for a misspelt field (`runnr`) and an
      option the scripted runner doesn't define (spec: config-hand-edits, "An invalid file is refused, never
      skipped").
      Done: `refuse_file_problems` maps `kinds.problems` to the file that holds the value.
- [ ] 1.4 The read-stability check: stat (size, mtime_ns, file id) before and after reading, through the platform
      seam (`platform/files.py`). Retry up to `config_read_attempts` (default 3) with `config_read_retry_seconds`
      (default 0.05), both in `core/defaults.py`, then `config.file-changing` (new code, in errors and the error
      schema). Verify with a test that injects a stat sequence: one change then still gives the final values; always
      changing is refused naming the file. Test on all three OSes in CI (file id on Windows).
      Done: `platform.files.file_stamp` (size, mtime_ns, st_dev, st_ino) and `read_steady`; injected-stamp tests. Done locally; ticked once Windows CI has run it.

## 2. The sweep: classify, compare, record (design D1, D3, D4, D5, D7, D9)

- [x] 2.1 `core/config/sweep.py`: classify each config path in D3's order (unknown, exactly what config renders, an
      untouched merge from troupe's versions, conflict markers with a person's side, absent, anything else). Use the
      existing `merges()`, `_merged_from_troupes` and `_MARKERS`, and add "conflicted with no markers left is read".
      Verify with a table-driven test over each class, including an older version troupe wrote (read, decision 1) and
      a conflicted file resolved by hand (read).
      Done: `core/config/sweep.py`; one test per class in `test_config_sweep.py` (older version read, clean merge and markers not read, hand-resolved conflict read, staged write skipped, unknown file refused).
- [x] 2.2 Additions and removals (D4): a new file adds its group; an absent `.md` unsets the character; an absent
      `.yaml` with its `.md` gone removes the actor; with the `.md` left it's `config.file-invalid`; an absent runtime
      file removes the runtime. Verify with a test per scenario in "Adding or deleting a file adds or removes what it
      held".
      Done: tests for a new actor, a deleted character, both files, a `.md` left alone (refused) and a runtime.
- [x] 2.3 Each read file's change via `changes.change()` on the group it owns, restricted to its fields (D5). Equal
      values give no entries. Verify: comment, reorder and re-indent record nothing and leave the bytes alone; 3 → 7
      is one entry; `.md` sets the whole text.
      Done: comment/order/indent give nothing; one value one entry; character whole; edit and undo nothing.
- [x] 2.4 Per-event lineage in one batch: extend `EventStore.record_with_lineage` (and `Command`) to take a lineage
      per event, all or nothing (D7). Verify with an event-store test that a batch whose third event fails validation
      writes nothing, and that each recorded line has its own lineage.
      Done: `EventStore.record_with_lineages`; tests for per-event lineage and an invalid third lineage writing nothing.
- [x] 2.5 Record each file's `Config.Changed`: one sweep `Command` (actor `unknown`, `via` `file`, no reason), one
      event per file, `vcs.source` with `before` (hash of what config rendered) and `after` (hash read), and `files`
      holding the read bytes' hash. Refuse the whole sweep if any file is refused. Verify with tests for the lineage
      scenarios (actor `unknown` even with `TROUPE_ACTOR` set; two files share a change id; the sweep's change id
      differs from the following `config set`'s), and that one invalid file stops every file's change.
      Done: `stream.record_with_edits`; tests for unknown author with `TROUPE_ACTOR` set, two files sharing a change id, the command's own change id differing, and one invalid file stopping all.
- [x] 2.6 Update the `config-changed` schema's description (no longer "one command records exactly one"), in
      `protocol/` and the package copy. Verify with the schema-copy test and `protocol_guard`.
      Done: schema and package copy, regenerated models and `docs/prompt-book/events.md`, aggregate docstring.
- [x] 2.7 The no-loop test (D9): on a theatre whose files a person formatted, run each config-using command twice. The
      second records nothing and writes nothing. Also: a staged write a change vouches for is finished before the
      sweep, and nothing is recorded for its target.
      Done: `test_every_command_run_twice_records_and_writes_nothing_the_second_time` (sync, config get, config set on a formatted file); the formatting survives.

## 3. Surgical write-back and compare-and-swap (design D6, D10)

- [x] 3.1 `core/config/writeback.py`: splice by composer node spans. Changed scalar or list replaced in place
      (sequence span trimmed to its last item's line, indentation kept); groups recursed; flow-style group replaced
      whole; new key after the last preceding sibling in schema or sorted order; removed key's lines deleted; the
      file's own line ending used. Verify with example tests for each scenario in config-files' "Write-back changes
      only what it must", byte for byte.
      Done: `core/config/writeback.py`; an example test per scenario, plus CRLF, no final newline, block scalars and groups' sorted order.
- [x] 3.2 Verify before staging: parse the spliced bytes and compare with the target values, else
      `config.write-back-failed` (new code) with nothing recorded. Verify with a test that forces a mismatch (a
      monkeypatched splice) and checks the refusal and that the event store and the file are unchanged.
      Done: a monkeypatched splice is refused with `config.write-back-failed`, naming `troupe sync --force`.
- [x] 3.3 The property test: generated formatted actor and runtime files (comments, blank lines, key orders,
      indentations, quoting, flow and block lists, CRLF) and random config changes. Every line outside the changed
      keys is unchanged, and the result reads as the target, or the write-back refuses (never a wrong file). Record
      any example it finds as a fixed test.
      Done: the property test found one bug (a group's new last key and a new key after the group, both inserted at the file's end, came out in the wrong order), fixed and kept as `test_a_groups_new_last_key_and_a_new_key_after_the_group_keep_their_order`. Measured over 4000 examples: every one written back, none refused.
- [x] 3.4 Wire write-back into `projection.plan`/`render`: an existing readable file's target bytes are the splice;
      a new file is rendered whole; `.md` replaced whole. A file whose values equal config is in line. Verify the
      existing `test_config_files.py` and `test_config_merge_files.py` still pass, with flush renamed to sync.
      Done: `syncing.sync_config` plans `writeback.targets` with the sweep's read files vouched; the existing files and merge suites pass, flush renamed to sync.
- [x] 3.5 Compare-and-swap (D10): under the lock, re-read each file just before replace or remove, and refuse
      `config.file-changing` if its bytes aren't the sweep's. Verify with a test that edits the file between the sweep
      and the replace (a hook in the test seam): refused, and the person's bytes are unchanged.
      Done at `execute`: it checks every path against the sweep's bytes before writing anything and again just before each replace; tests for a file changed meanwhile (refused, left alone) and one still as read. The command-level scenario runs once 5.2 wires it.

## 4. Conflicts resolved by hand (design D8)

- [x] 4.1 While config has conflicts, count a read file's values at conflicting paths as set (deleted file: unset),
      and check resolution on the union of the sweep's entries and the command's operations. Record the settle, the
      sweep's changes and the command's change in one batch. Verify with tests over real two-branch git theatres for
      each scenario in "Hand edits resolve config's conflicts": an edit resolves; a value matching neither side; a
      partial resolution refused naming what's left, with the file kept; a partial finished by `config set`; taking a
      side with `git checkout --theirs`; an untouched merge resolves nothing.
      Done: `test_cli_config_hand_conflicts.py` on real two-branch theatres through the CLI: an edit resolves, a value matching neither side, a partial resolution refused naming what's left with the file kept, a partial finished by `config set` (one batch: settle, hand edit, change), `git checkout --theirs`, two values in one cleanly merged file, and an untouched merge resolving nothing.
- [x] 4.2 Name every resolved conflict (owner, 2026-11-21): a `config.conflict-resolved` notice per resolved value
      (path, file, value taken or unset, the conflicting change ids), from every command and, saying "would", from a
      rehearsal. Catalogue it in `protocol/schemas/notice.schema.json` (and the package copy). Verify with tests for
      each scenario in "Every conflict a hand edit resolves is named", and that the two-values-in-one-file test sees
      two notices.
      Done: `config.conflict-resolved` from sync, perform (named before the run starts) and rehearsals ("would resolve"); the two-values test sees both named.
- [x] 4.3 `config get` with a partial resolution: records nothing, shows the conflicts, and adds the
      `config.hand-edit-unrecorded` notice naming the file and the values still unset. Verify with a test. Add the
      notice code wherever notices are catalogued.
      Done: `config get` records nothing, shows the conflict (both values, one pair of changes), and `config.hand-edit-unrecorded` names the file and the value left.
- [ ] 4.4 Update `contributing/config.md` and `docs/stagecraft/hand-edit-config.md`'s "Branches" section: a hand edit
      resolves a conflict, as `config set` does.
      `contributing/config.md` is done ("The sweep"); `hand-edit-config.md`'s Branches section is rewritten with 6.2, and this is ticked then.

## 5. `troupe sync` replaces `troupe flush` (design D1, D11)

- [x] 5.1 Protocol: rename `client/flush-{request,result,update}.schema.json` to `sync-*`, method `sync`; add the
      result's `edits` (per file: path, change id, entries). Update `client/config.schema.json`, the package copies,
      `core/client/messages.py`, `dispatch.py` and the generated types. Record the breaking rename in
      `protocol/CHANGELOG.md`. Verify with `test_client_schemas.py` and `test_client_messages.py` (round trip from
      generated messages).
      Done: `client/sync-*` schemas with `edits`, `SyncRequest`/`SyncResult`/`HandEdit`, dispatch; client schema and message round-trip tests pass. The breaking rename goes in the commit's footer, since release-please writes the changelog.
- [x] 5.2 Core: replace `sync_files` and `flush_files` with one `sync()` that sweeps then writes, used by `perform`,
      `config set`, `config unset`, `config get` (sweep only, no writes) and the `sync` method. `--force` replaces
      refused files keeping a copy, and still records the valid ones. Report each recorded hand edit as the
      `config.hand-edit-recorded` notice. Verify with tests for "Every command that uses config sweeps first"
      (perform rehearsal shows the edited runner; get prints it and records it; `status` doesn't sweep) and "Force
      replaces a file and keeps a copy".
      Done: `core/config/syncing.py`; every command goes through it (perform rehearses the sync first so a refused perform writes nothing, then syncs for real before the run). Tests in `test_config_sync.py`. Found while wiring: a missing file is a removal only if this clone had it at its last sync (`local/config/present.json`), agreed through the orchestrator and recorded on #119, spec and D4.
- [x] 5.3 Rehearsal: `--rehearse` on every command shows the sweep's would-be edits, records nothing and writes
      nothing, and exits with "would change" or the refusal's code. Verify with tests for "A sweep can be rehearsed"
      and the cli exit-code scenarios.
      Done: rehearsed sync and config set show the sweep's would-be edits (`rehearsal: true`) and record and write nothing; the cli exit-code scenarios pass.
- [x] 5.4 CLI: `troupe sync` (`--force`, `--rehearse`) in `cli/table.py` and `cli/config.py`; no `troupe flush` (an
      unknown command). Render hand edits and their notices. Verify with `test_cli_config.py` cases, including
      "Flush is gone". Check that the command table still loads only its own handlers (cli-starts-fast tests).
      Done: `troupe sync` with `--force` and `--rehearse`; `troupe flush` is an unknown command (tested); hand edits rendered.
- [ ] 5.5 Rename every "troupe flush" in messages, errors, notices and tests to `troupe sync` (`rg -n "flush"` across
      `packages/troupe/src`, `packages/troupe/tests`, `docs`, `contributing`, `protocol`). Verify with an `rg` that
      finds no user-facing "flush" (the stream-flush uses in runners and the store stay).
      Source, schemas, tests and the CLI reference are done; `docs/stagecraft/hand-edit-config.md` is rewritten in 6.2, and this is ticked then.
- [x] 5.6 Update the existing tests whose behaviour the decisions changed: a deleted file is now a removal; an older
      version troupe wrote is now read as an edit; a clean merge edited after git made it, and a merge older than
      HEAD, are read as edits; a valid hand edit before `config set` is recorded, not refused. Verify each against
      its scenario.
      Done: the tests the decisions changed are rewritten under names that say what they check now (a deletion after a sync removes, a file never had is written, an edit before config set is recorded, an edited or older clean merge is read as an edit, an invalid edit is refused); the perform harness writes its files as config set would.

## 6. The first run edits the character file again (design D12)

- [ ] 6.1 `cli/init.py`'s `render_init`: the character line says to edit `.troupe/actors/lead.md`. Remove the D8
      comment. Verify with the cli test "The character is changed by editing its file": init an audition, write
      text into `lead.md`, `troupe perform lead --rehearse` isn't refused, and `config get actors.lead.character`
      prints the text.
- [ ] 6.2 Docs: `docs/opening-night/first-performance.md` ("Write its character"), `first-theatre.md`'s "Config"
      section, and `docs/prompt-book/cli.md` (`troupe init`, and `troupe sync` in place of `troupe flush`). Rewrite
      `docs/stagecraft/hand-edit-config.md` for the sweep: what counts as a change, the mid-save guard, unknown author,
      restores and deletions, write-back. Verify with the docs checks in `scripts/check.py` and rendered anchors for
      changed headings.

## 7. Integration

- [ ] 7.1 An end-to-end test through the CLI in a real git theatre: init an audition, hand-edit `lead.yaml` (a comment
      and a model change) and `lead.md`, run `troupe perform lead --rehearse`, `troupe config set` another value, then
      `troupe sync`. Check the events (two hand-edit changes by `unknown`, then the person's change), the files (the
      comment and formatting kept), and that a final `troupe sync --rehearse` exits 0.
- [ ] 7.2 Ask the orchestrator for a slot, then run `uv run scripts/check.py` (log to a scratch file) and fix what it
      finds. Run `mypy --platform win32` on the changed modules (the stat and file-id seam).
- [ ] 7.3 `openspec validate hand-edit-sweep --strict`, and measure every MODIFIED requirement's collapsed text
      (≤ 500 characters).

## Workflow follow-up

- Raise the troupe-run/infrastructure issue and PR adding `config-hand-edits`' Purpose to
  `oob/troupe-spec-purposes.json` (on the board). It merges after this PR, and this PR doesn't wait on it.
- Draft PR closing #119; act on Claude's review by slice; mark ready; archive on the branch; the owner merges.
- After the merge, check #119 is closed and its card says Done, and comment with the PR and the archived change.
