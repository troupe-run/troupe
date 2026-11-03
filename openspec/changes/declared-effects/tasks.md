# Tasks

## 1. The protocol: one pattern, the actor, run start and init

- [x] 1.1 Add `protocol/schemas/effects.schema.json` with `$defs/pattern` (D1's regex) and `$defs/declaration` (all
  three lists required), and reference the pattern from `config/actor.schema.json`'s new closed `effects` group.
  Verify the protocol strictness check passes and `uv run scripts/docs_reference.py` regenerates
  `docs/prompt-book/config-schema.md` with `effects`.
- [x] 1.2 Write the hypothesis test that the schema's pattern and the SDK's `pattern_regex` plus the `.git`/`.troupe`
  first-part rule accept exactly the same strings, generated and near misses. Verify it passes, and fails when a rule
  is dropped from either (effects spec, "The schema and the SDK agree").
- [x] 1.3 Add `effects` and `scratch` (required) to `runner/run-start.schema.json`, and `effects`
  (`checked | translated`, required) to `init` in `run-event.schema.json`. Verify the schema tests: a read-only
  declaration validates, one with a list missing doesn't, an `init` without `effects` doesn't (runner-protocol delta).
- [x] 1.4 Regenerate core's config types from the actor schema. Verify `scripts/check.py`'s generated-types check
  passes and the type/schema agreement property test covers `effects`.

## 2. The SDK: declaration, translation seam, tools

- [x] 2.1 Add `scratch` and `effects` to `RunStartParams`, and `effects` to the `init` event type. Verify the SDK's
  schema-agreement tests pass, and fail when either field is removed from a type.
- [x] 2.2 Add `Declaration.from_run_start`, `absolute()`, `scratch_absolute()` and the `EffectsTranslation` protocol
  (D7). Verify unit tests: a `write` run start allows `out/a.txt` only; a malformed pattern raises naming the effect;
  `C:\work\theatre` with `out/**` normalises to `/c/work/theatre/out/**` (run on every OS by building Windows paths
  with `PureWindowsPath`).
- [ ] 2.3 `Tools` takes `scratch`: absolute paths inside it need no effect; moves across the boundary need the
  workspace end's effect; links out of scratch are refused; no scratch means an absolute path is an error. Verify the
  runner-tools delta's scenarios as tests against the fake model, on Linux, macOS and Windows in CI.
- [x] 2.4 Refuse changes under the workspace's top-level `.troupe` (reads allowed), and name scratch in the tool
  definitions. Verify the `.troupe` write and move scenarios, a `Read` of `.troupe/actors/x.yaml` succeeding, and
  `Write`'s description naming the scratch path.

## 3. Core: config rules, scratch, run start

- [x] 3.1 In `config/kinds.py`, validate `effects` and check each `expect` path against `write` or `move` (D2),
  with the exact `troupe config set` fix. Verify tests for each effects-spec scenario under "Every expected file is
  covered", including one command setting both, and that a merged config breaking the rule is a conflict.
- [x] 3.2 Add the `RUN_SCRATCH_ROOT` setting in `defaults.py` (default from the platform seam), refuse one inside the
  theatre, make scratch in the run host before the runner starts and remove it in the run's `finally`, with a
  `run.scratch-not-removed` notice when removal fails (design D6). Verify tests: scratch exists and is empty at run
  start, outside the workspace, is gone after `succeeded` and `failed` runs; a failed removal (simulated, so it's the
  same on every OS) is a notice, not a failed run; a root inside the theatre is refused with nothing recorded.
- [x] 3.3 The host sends the declaration and scratch in `run/start`, and checks `init.effects`; the conformance suite
  checks both. Verify `tests` for "The effects reach the runner" and the conformance scenario for an `init` without
  `effects`, and that the scripted and Claude Code runners pass the suite.

- [x] 3.4 Make the local stage's `stage.effects-unenforced` refusal and its fix say that changes outside the
  workspace are neither prevented nor detected, and that only a stage that enforces effects contains them. Verify
  the stages test for the default-policy refusal checks the new wording, and the effects-spec scenario that a write
  outside the workspace passes the audit with lineage `unenforced`.

## 4. Core: the audit

- [ ] 4.1 Add `file_states(root, at=None)` to the VCS port, with the git adapter (D4: `ls-files -s`, `status
  --porcelain=v2 -z`, `hash-object`, `ls-tree -r`) and the files adapter (walk and hash). Verify adapter tests: clean,
  modified, untracked, ignored (left out), `.git` and `.troupe/` left out, a committed change counted against a base
  commit, and a path with spaces and non-ASCII characters, on every OS.
- [x] 4.2 Add the `DeclaredEffects` check and the `Combined` check (D3), with `effects.outside-declared` and
  `effects.check-failed` errors whose `details.changes` follow D3. Verify unit tests for each effects-spec scenario
  under "Each kind of change needs its own effect", including deterministic move pairing with two identical files.
- [x] 4.3 Wire the audit into `perform` for worktree and theatre runs, replacing `effect_check_for`'s no-check
  branch. Verify end-to-end tests with the scripted runner's raw `write` step: a write outside the declaration fails
  the run naming the path; `expect: []` still audits; an ignored build output passes; a pre-existing uncommitted
  change left alone passes; a concurrent edit in a theatre run fails with the message saying so.
- [x] 4.4 Show the declaration and a failed audit on `troupe perform`'s output, from the structured error. Verify a CLI
  test for "A failed audit on the command line".

## 5. The scripted runner

- [x] 5.1 Add the `tool` step (D9) to the options schema and the runner, with `isError` matching, and report
  `init.effects: checked`. Verify the scripted-runner delta's scenarios, and the options schema still passes the
  strictness check.
- [ ] 5.2 Write the done-when tests through `troupe perform` with `tool` steps: a read-only actor can `Read` but not
  `Write`; `write` for `out/**` writes `out/a.txt` and is refused `src/a.py`; `delete` and `move` each work only where
  declared, and `write` allows neither. Verify they pass on Linux, macOS and Windows in CI, and lineage on each run's
  events says `unenforced` (stages delta).

## 6. The Claude Code runner

- [ ] 6.1 Add `troupe_runner_claude_code.permissions`, an `EffectsTranslation` (D8): `dontAsk` or `plan`, `Edit(//…)`
  allow rules from `write` and scratch, denies for `.git` and `.troupe`, `--add-dir` and `TMPDIR`/`TMP`/`TEMP` for
  scratch, `sandbox.autoAllowBashIfSandboxed: false`, `init.effects: translated`. Verify unit tests for each
  claude-code-runner delta scenario on settings and command lines, including the Windows `//c/…` form.
- [ ] 6.2 Refuse widening options with `claude-code.widens-effects`, and untranslatable patterns with
  `claude-code.untranslatable-pattern`; publish both in the runner's error codes schema. Verify the scenarios for
  `acceptEdits`, `Edit(src/**)` in `allowedTools`, a denied edit rule passing, and `app/[id]/page.tsx`.
- [ ] 6.3 Add the stdio MCP server for `Delete` and `Move` (standard library only), its config in the private
  directory, `--mcp-config` only when `delete` or `move` is declared, and its allow rules. Verify tests that drive the
  server over stdio (initialize, tools/list, a declared delete, a refused move), and that a write-only actor's command
  line has no `--mcp-config`.
- [ ] 6.4 Send the `log` warnings for allowed shell rules and loaded setting sources. Verify tests for both scenarios.
- [ ] 6.5 Capture fixtures from a current Claude Code for a run whose edit is denied by the translated rules and one
  that calls `mcp__troupe__Delete`, and run the opt-in live test once with `write` declared. Verify the fixtures pass
  their mapping tests, and record the live test's Claude Code version and result in the pull request.

## 7. Auditions, docs and specs

- [ ] 7.1 Update the auditions (D10). Verify the config delta's audition scenarios, and that the scripted audition
  performed offline succeeds with its audit passed.
- [ ] 7.2 Document effects for people: what each list allows, the read-only default, `expect` inside `write`, the
  audit, scratch, that none of it is enforcement, and that changes outside the workspace are neither prevented nor
  detected on the local stage, in the user docs page on actors and the regenerated schema page.
  Verify `uv run scripts/docs_reference.py --check` passes and the docs build's link check passes.
- [ ] 7.3 Update `plugins/runner-claude-code/README.md` (options, the translation, delete and move, what shell rules
  can still do), `plugins/README.md` and `contributing/runners.md` (the declaration, `init.effects`, the translation
  seam). Verify every option and error code the README names is in the published schemas (the README test).
- [ ] 7.4 Run `openspec validate declared-effects --strict` and `uv run scripts/check.py`. Verify both pass.

## Workflow follow-up

- Open the infrastructure pull request adding the `effects` spec's Purpose to `oob/troupe-spec-purposes.json`
  (`cap:effects`, `cap:config`); it merges after this one.
- Draft pull request with `Closes #241`; act on Claude's review; mark ready; archive on the branch; the owner merges.
- After merge: comment on #241 with the PR and the archived change, close it if needed, and check its card is Done.
