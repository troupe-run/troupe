# Tasks

Each group lands as its own push on one pull request, in this order, and is reviewable on its own (design, Risks).

## 1. The `flows` config kind

- [x] 1.1 Add `protocol/schemas/config/flow.schema.json` (steps, at least one, each with `actor`, optional `direction`
  and `approvers`), regenerate the models, and package the schemas. Verify: config schema tests accept a flow and
  refuse an empty step list, an unknown field and a malformed approvers list.
- [x] 1.2 Add `FLOWS` to `kinds.py` with its cross-kind rules (D1): a missing actor, a theatre actor, a name shared
  with an actor, and removing or moving an actor a flow uses. Verify: unit tests for each refusal naming flow, step
  and rule, and a merge test showing a rule broken across branches is a conflict.
- [x] 1.3 Project flows to `.troupe/flows/<name>.yaml`, swept like other config files. Verify: config-files tests for
  a written flow, a hand edit swept with an `unknown` actor, and a removed flow's file.
- [x] 1.4 Let `config mv` rename a flow, and carry an actor's rename into the flow steps that name it. Verify: rename
  tests for both, including an actor named twice in one flow.
- [x] 1.5 Document the kind in `docs/prompt-book/config-schema.md` (generated) and `docs/stagecraft/build-a-flow.md`
  (how to write one). Verify: the docs and reference checks pass.

## 2. Worktrees built on the work so far

- [x] 2.1 Add `apply_in_worktree(path, diff) -> baseline` to the VCS port and the git adapter (D3), refusing a diff
  that doesn't apply, all or nothing. Verify: adapter tests on a worktree with an applied diff, the returned baseline
  equal to `write-tree`, and a failing diff leaving the worktree unchanged.
- [x] 2.2 Capture a step's `sofar` diff against the performance's base beside its own diff (D4), and add `sofar` to
  `run-ended`'s changes and `builtOn` to the run start's workspace. Verify: workspace tests for two captures, and
  schema tests for the new fields.

## 3. Performing a flow

- [x] 3.1 Split `perform` into a plan and a driver (D2) with every existing perform test unchanged and passing. Verify:
  the full perform and run test suites pass with no test edited for behaviour.
- [ ] 3.2 Resolve `troupe perform <flow>` to a plan of its steps, with every refusal checked over every step before
  anything is recorded, and a rehearsal covering all of them. Verify: integration tests for a two-step flow's records,
  and a rehearsal refused by its second step recording nothing.
- [ ] 3.3 Build each step's worktree on the work so far (D3), with its audit judging only its own changes. Verify: an
  integration test where step 2 reads step 1's file, step 2's diff omits step 1's change, and the theatre's files are
  untouched mid-flow.
- [ ] 3.4 Assemble each step's direction (D6) and write the history files into its worktree. Verify: tests of step 3's
  stored direction, of each history file's content, of history never in a diff, and of a runtime credential absent
  from every history file.
- [ ] 3.5 Gates between steps (D5): resolved approvers with `step` as a source, `Run.ChangesApproved` with its schema and
  lineage rule, the step's worktree removed once the next is made, and the last step's gate applying `sofar`. Verify:
  integration tests for troupe letting a step through, a person-first step waiting (exit 4, no end), a landing flow,
  and a last step with no changes still landing the flow's work.
- [ ] 3.6 Perform's updates and the CLI progress lines for a flow (`step <k>/<n> <actor>`). Verify: client schema tests
  and a CLI test of a two-step flow's standard error.

## 4. Carrying on, stopping, settling

- [ ] 4.1 `config_at(store, heads)`, reading config as at the performance's start (D7). Verify: unit tests reading an
  actor's options at an earlier version after a later change, and through a merge.
- [ ] 4.2 `approve` at a step before the last records `Run.ChangesApproved`, then drives the remaining steps with
  perform's updates and exit codes; `--rehearse` checks them and runs nothing. Verify: integration tests for carrying
  on to a landing, config edited while waiting, and a rehearsal; a CLI test of approve's output and exit code.
- [ ] 4.3 `reject` removes every worktree a performance still has, and ends it `rejected`. Verify: a test rejecting a
  waiting step of a three-step flow.
- [ ] 4.4 A failed or cancelled flow stops whole (D8): `accept <performance>` applies `sofar`, `discard` removes the
  worktree, and naming any of its runs is refused with `performance.settled-whole` (catalogued). Verify: integration
  tests for a failed second step accepted whole and discarded whole, Ctrl-C mid-flow, and the refusal.

## 5. Reading flows back

- [ ] 5.1 `resolve` returns a run or a performance (D9), with approve, reject, accept, discard and diff acting as the
  performances spec says, and `performance.several-runs` removed from the catalogue. Verify: tests for each command
  through a flow's performance id, and `gate.no-cue` when nothing waits.
- [ ] 5.2 Status lists performance summaries (D10), a flow's line with its progress and runs indented under it, and
  `status <performance>` showing every step. Verify: client schema tests and CLI tests for a waiting, failed and
  completed flow, and an unchanged one-step line.
- [ ] 5.3 `logs <performance>` returns every step's log, and `--follow` follows across steps. Verify: an integration
  test following a two-step flow from another process to its end.
- [ ] 5.4 `troupe diff <performance>` shows the latest `sofar`. Verify: a test diffing a flow failed at step 2.

## 6. Docs and integration

- [ ] 6.1 Write `docs/the-company/flows.md` in full, and update performances-and-runs, gates-and-decisions, lineage,
  the glossary (flow, step), the events and CLI references, and `contributing/runs.md`. Verify: the docs checks pass.
- [ ] 6.2 Run `openspec validate actor-sequences --strict`, the spec size gate, and the full `uv run scripts/check.py`
  with its output kept. Verify: all pass.

## Workflow follow-up

- Draft PR closing #124, one push per group above. Act on Claude's review of each push.
- Archive before marking ready.
- After the merge: troupe-run/infrastructure records the `flows` spec's Purpose and updates `cap:config`'s
  description to name flows.
