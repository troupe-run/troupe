# Tasks

## 1. Workspace and packages

- [ ] 1.1 Create `packages/troupe-store-text`, `packages/troupe-vcs-git`, `packages/troupe-vcs-files` and
  `packages/troupe-identity-local` (src layout, `py.typed`, licence, README, entry points per design D1). Add them to
  the dev group, and add `eventsourcing>=9.5.5,<9.6` (runtime, in `troupe` and `troupe-store-text`) and `pycryptodome`
  (dev). Verify `uv sync` succeeds and `uv run python -c "import troupe_store_text, troupe_vcs_git, troupe_vcs_files, troupe_identity_local"` exits 0
- [ ] 1.2 Extend `pyproject.toml` tool config (ruff `src`, mypy `files` and `mypy_path`, pytest `testpaths`) to cover the
  new packages, and add the import contracts from design D1: `troupe` imports no adapter package, and `troupe.cli`
  imports no recorder. Verify each contract fails on a deliberate violation (record the output for the PR), and
  `uv run scripts/check.py` passes

## 2. Platform: bounded commands (on the runner contract's processes module)

Starts once the runner contract's `troupe.platform.processes` (`run_to_completion`, `EnvironmentPolicy`,
`build_environment`, `kill_tree`) is on main. Rebase onto main first; never merge main in. Groups 1, 3, 6 to 9 (with
the filesystem adapter) don't wait for it. Only this group, 4.2, 4.3 and 5.2 do.

If apply reaches those tasks before the runner contract merges, `event-store` may rebase onto the runner contract's
commits (`eab458c`, `46dd1b6`) to build on the real API, then rebase onto main once the runner contract lands.
Waiting for main stays the default. Either way, rebase only, never merge.

- [ ] 2.1 After rebasing onto main, confirm the runner contract's `platform` spec in `openspec/specs/platform` holds
  the environment-policy, narrowing, whole-tree and run-to-completion requirements this change relies on (design D11).
  Verify `openspec validate event-store --strict` passes, and the git adapter's timeout test (4.2) shows the tree
  killed on all three CI platforms
- [ ] 2.2 Wrap the platform errors in `troupe.core` as `command.timeout`, `command.not-found`,
  `command.output-too-large` (naming the command) and `environment.policy-invalid`, and document the git adapter's
  limits in `docs/platform.md`. Verify the error-schema test and `test_platform_docs.py` pass, and that narrowing
  `GIT_ENVIRONMENT` wider is refused with `environment.policy-invalid`

## 3. Protocol: lineage, records and notices

- [ ] 3.1 Write `protocol/schemas/lineage.schema.json`, `event-record.schema.json` (header and event lines) and
  `notice.schema.json` (design D3, D8, D12), and list them in `protocol/README.md`. Verify with schema tests that
  valid and invalid examples (a null actor, `unknown` with an ID, an extra field, `NaN`, a null or missing `cause`, an
  unknown `cause.kind`, an event cause that isn't a `sha256:` hash) are accepted and rejected as intended
- [ ] 3.2 Add `troupe.core.notices` (declared codes, mirroring `errors.CODES`) and the new error codes from design D12.
  Verify with a test that serialises every declared notice and error and validates each against its schema

## 4. VCS port and adapters

- [ ] 4.1 Define the VCS port in `troupe.core.vcs` (adapter name, branch, HEAD, `is_committed(path)`, configured
  identity). Implement `troupe_vcs_files`. Verify with tests for the `vcs` spec's plain-filesystem requirement
- [ ] 4.2 Implement `troupe_vcs_git` over `run_to_completion`, with `GIT_ENVIRONMENT`, `GIT_TIMEOUT_SECONDS` and
  `GIT_MAX_OUTPUT_BYTES` as named defaults in `troupe_vcs_git.defaults` (design D11), and `vcs.failed` for git
  errors. Verify with tests against real temporary repositories: fresh repository (branch, no HEAD), detached HEAD,
  staged-only file counts as committed, `user.email` unset or empty is none, git missing from `PATH`, and a hung git
  (a stub on `PATH` that sleeps) times out with its tree killed
- [ ] 4.3 Verify the git adapter's environment policy with tests for every scenario of the `vcs` spec's
  environment-policy requirement: global config under a temporary `HOME` (and `XDG_CONFIG_HOME`) found, hook-time
  `GIT_DIR`/`GIT_WORK_TREE` ignored, `AWS_SECRET_ACCESS_KEY` not passed, and the installed git's
  `git rev-parse --local-env-vars` all in `never`
- [ ] 4.4 Implement `branch_token()` (design D4) for both adapters. Verify that a session makes one git call for the
  token path and none per batch while the branch is unchanged (count calls through an injected runner), and that
  switching branches mid-session changes the token and starts a new segment

## 5. Identity

- [ ] 5.1 Implement the chain in `troupe.core.identity`: sources by entry-point name, `IDENTITY_CHAIN` default,
  `identity.unknown-source`, `identity.unresolved` (listing the sources tried). Verify with tests for "first that
  answers wins", "reordering the chain", and "nothing resolves, nothing written"
- [ ] 5.2 Implement the `env`, `vcs` and `os-login` sources in `troupe_identity_local` (design D9). Verify with tests
  for every `identity` spec scenario, including a malformed `TROUPE_ACTOR` and two `user.email` values (`identity.ambiguous`) that
  fail rather than fall through, an unset `user.email` that does fall through, the
  `vcs` source answering nothing under the filesystem adapter, and `user.email` set only in a global config under
  a temporary `HOME` resolving through the git adapter's real policy (not falling through to the OS login)

## 6. Recorder: segments, records and the library suite

- [ ] 6.1 Implement the record codec (design D3): canonical JSON, inline `state` only when exact (else `state_b64`),
  content hash leaving out `timestamp` and `lineage`, `format` check. Verify with Hypothesis property tests: arbitrary
  state bytes round-trip exactly, inline lines are strict JSON, the hash ignores lineage and time, the hash
  changes with any content field, and a line with a duplicate key or a `NaN`/`Infinity`/`-Infinity` inserted
  anywhere fails with `events.malformed-record` (file and line) while the same line without it reads
- [ ] 6.2 Implement segments and sessions (design D4): a monotonic ULID session ID, the header written with the first
  batch, a new segment on a branch change, a batch as one fsynced append, and an incomplete trailing batch left out
  with `events.incomplete-batch` while malformed lines elsewhere fail. Verify with tests for each scenario, including
  one that truncates a batch mid-line
- [ ] 6.3 Implement the aggregate and application recorders over the local order log (design D5): rescan of new
  bytes, uniqueness over visible events, dense IDs, and the thread lock taken before `directory_lock(.troupe/local)`
  (design D10). Write `.troupe/.gitignore` and `.troupe/.gitattributes` only if missing. Verify with
  `AggregateRecorderTestCase`, `ApplicationRecorderTestCase` and `NonInterleavingNotificationIDsBaseCase`
  unmodified, and a test that reads create no files
- [ ] 6.4 Implement `listen`/`unlisten` and `subscribe` via `ListenNotifySubscription`, with the cross-process poll at
  `SUBSCRIBE_POLL_SECONDS`. Verify with the suite's `optional_test_insert_subscribe` and a two-process test where
  one process's write wakes the other's subscription
- [ ] 6.5 Implement the tracking and process recorders (epoch-scoped tracking, a torn last line ignored, damage
  elsewhere failing, duplicate keys and non-finite numbers refused) and the `InfrastructureFactory` (parameterised, `PERSISTENCE_MODULE=troupe_store_text`).
  Verify with `TrackingRecorderTestCase`, `ProcessRecorderTestCase` and `InfrastructureFactoryTestCase` unmodified.
  Add fixture tests for a duplicate key and a `NaN` in the order log and the tracking file. Then run the whole library
  suite and confirm none is skipped or replaced
- [ ] 6.6 Verify cross-process behaviour on all three platforms: two processes racing for the same stream version
  (exactly one integrity error), and a waiting writer that announces and times out. Verify `git status` shows no
  lock file

## 7. Ordering across branches, merges and removals

- [ ] 7.1 Implement replay of visible, unordered events (topological, then session, then line) and the crash window
  self-heal. Verify with tests using real git repositories: a merge that appends without renumbering, with events
  recorded earlier than ones already numbered; IDs surviving a restart; no tracked file holding notification IDs;
  and a two-branch merge with no conflicts in `.troupe/events/`
- [ ] 7.2 Implement other-branch visibility (design D7): uncommitted segments from another branch left out of reads and
  uniqueness checks, with `events.other-branch`, and committed segments always read. Verify with the untracked
  `git switch` scenario and the merged-branch scenario
- [ ] 7.3 Implement order rebuild with a new epoch and `events.order-rebuilt`, and tracking reset by epoch. Verify by
  deleting an uncommitted segment: the order is rebuilt, the notice names the reason, and a follower restarts from 0
- [ ] 7.4 Implement missing-parent refusal (`events.missing-parent`, naming the dependent file and line, the missing
  ID, and the fix). Verify with the "parent's file was removed by hand" scenario, including a parent that is only in
  an other-branch segment
- [ ] 7.5 Implement equal-ID deduplication and `recordings(id)`. Verify with two clones recording the same change
  with different actors: after a merge, reads return one event and `recordings` returns both lineages
- [ ] 7.6 Add a Hypothesis state-machine test over random branch, record, commit, switch, merge and delete-file
  sequences on a real repository. Verify the invariants hold after every step: IDs dense, no issued ID renumbered
  except after a reported rebuild, every visible event ordered exactly once, and no merge conflicts in `events/`

## 8. Forks and settling

- [ ] 8.1 Implement parents, head detection, `forks()` and `events.stream-forked` on `select_events` and on insert.
  Verify with the "two branches append to one stream" and "appending to a forked stream" scenarios
- [ ] 8.2 Implement the settling-event base (Snapshot mechanics), `settle()`, `events.settle-incomplete`, loading
  from the latest settling event, and `history(stream)`. Verify with a test aggregate: a settled stream loads to the
  settled state plus later events, a settle naming one head fails, and history includes both branches

## 9. The event-store service and lineage

- [ ] 9.1 Implement lineage types in `troupe.core.events` (actor kinds, via, UTC time from an injectable clock, change
  ID per command, `cause` in both kinds, approvals, VCS state with theatre-relative `/` paths and `sha256:` hashes). Verify every built
  shape validates against `lineage.schema.json`
- [ ] 9.2 Implement the service: open a theatre with VCS, identity and store adapters by name. Resolve identity
  before any write, validate lineage (`events.lineage-invalid`) and its cause (a command cause equal to `change`;
  `events.cause-unknown` for an event cause that isn't visible) before calling the recorder, map `IntegrityError` to
  `events.version-conflict`, and return notices with reads. Verify with tests for every `lineage` spec scenario,
  including that one command's events share a change ID and an invalid lineage writes nothing
- [ ] 9.3 Verify the abandoned-edit rules from #1 end to end through the service: an edit and its revert both kept
  (history 3, 5, 3), stash and pop events all present in order, and an unknown-actor `via: file` event with before
  and after hashes recorded and validated
- [ ] 9.4 Implement `record_reaction(trigger, …)` (design D8): it inherits the trigger's `change` and sets an event cause.
  Verify with tests for the `lineage` spec's cause scenarios: the E1 → E2, E3, E4 example, a reaction to a reaction
  keeping the original `change`, an unknown cause refused with nothing written, and a mismatched command cause refused
- [ ] 9.5 Write `docs/event-store.md`: layout, record format, ordering, forks, visibility, notices, identity chain and its absent-vs-malformed rule, correlation and cause,
  defaults table, and the measured cold-load time for 10,000 segments (a benchmark script under `scripts/`). Link
  it from the README. Extend the docs test so the defaults table matches `troupe.core.defaults` exactly. Verify the
  test passes

## 10. Integration

- [ ] 10.1 Runner-contract check: read the `runner-contract` change's artifacts (#34) as they stand, compare them with
  design.md D-Runner, revise any point they contradict (with the owner's agreement), and record the outcome in
  the PR. Verify D-Runner matches #34's design, or lists each remaining difference
- [ ] 10.2 Run `uv run scripts/check.py` locally, push, and verify every CI job passes on Linux, macOS and Windows
  (3.12 and 3.13)

## Workflow follow-up

- Open the PR with `Closes #35`, and comment on #9 with design D9 for the owner to confirm or amend.
- Run `/opsx:archive` on the branch before merging, so the PR lands code, tests and specs together.
- After the merge, comment on #35 (and #1, whose details this change settles in the `event-store` spec) with the PR
  and the archived change.
