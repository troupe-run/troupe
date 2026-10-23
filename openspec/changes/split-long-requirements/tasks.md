# Tasks

## 1. Tests for the added requirements, run against main first (design D4)

Each test here checks behaviour the code already has. Write it, run it before any spec or other test edit, and show
it passing. If one fails, stop: open a Bug issue on the roadmap board naming the failing requirement, and ask the
owner whether to fix it in this change.

- [x] 1.1 In `packages/troupe/tests/test_run_host.py`, add a test under `# Requirement: The runner takes direction,
  character and configuration only from its run start (spec: runner-protocol)`. It runs a scripted actor with a
  character, a direction and an option, each holding a unique marker, and asserts that neither the argv the host
  spawns nor the environment it passes holds any marker. If the harness can't observe argv and environment without a
  production change, stop and ask. Verify with `uv run pytest packages/troupe/tests/test_run_host.py -k <name>`.
- [x] 1.2 In `plugins/runner-scripted/tests/test_scripted_schemas.py`, add a test under `# Requirement: A script's
  steps cover what a runner can send or do`. It asserts that `options.schema.json`'s `step` alternatives include
  `event`, `transcript`, `stderr`, `wait`, `writeFile`, `hang`, `exit` and `rawStdout` as their `required` key. It
  checks inclusion, not equality (design D3). Verify it passes, then that it fails with one kind removed from a copy
  of the schema.
- [x] 1.3 In `plugins/runner-scripted/tests/test_scripted_runner.py`, add two tests under `# Requirement: Steps that
  don't wait play without reading troupe's messages`. Both use `_played_with_everything_queued` with
  `onCancel: "ignore"` and a queued `run/cancel`:
  - a `wait` step followed by a `transcript` step: the cancel's answer comes before the transcript record;
  - a replayed recording with `replayDelays: true` and a delay between two records, then a `transcript` step: the
    cancel's answer comes before the last recorded record, and every recorded event is sent.

  They assert message order, not elapsed time. Verify both pass with `uv run pytest` on the file, run five times.

## 2. Split the requirements and point the tests at them (design D1, D2, D5)

- [ ] 2.1 Check the deltas against main's specs: each MODIFIED block keeps main's header and every scenario word for
  word, and the descriptions of the original plus the added requirements hold every sentence of main's description.
  Only D1's two "stand alone" edits differ. Verify by diffing main's requirement block against the delta's blocks
  (`git show main:openspec/specs/<spec>/spec.md`), and with `openspec validate split-long-requirements --strict`.
- [ ] 2.2 In `packages/troupe/tests/test_runner_schemas.py`, replace the `:372` comment. Put
  `test_the_contract_alone_accepts_only_empty_options` under `# Requirement: Run start options are an extension
  point`, and `test_with_a_runners_schema_bound_its_options_validate_and_an_unknown_key_does_not` under
  `# Requirement: Run start carries everything the runner may use`. Verify with
  `uv run pytest packages/troupe/tests/test_runner_schemas.py`.
- [ ] 2.3 In `plugins/runner-scripted/tests/test_scripted_runner.py`, drop the bracket from the `:380` comment, so the
  two existing message-timing tests sit under `# Requirement: A script is a list of steps played in order`. Verify
  with `uv run pytest plugins/runner-scripted/tests/test_scripted_runner.py`.
- [ ] 2.4 Check that every `# Requirement:` comment in the repository naming a `runner-protocol` or `scripted-runner`
  requirement matches a header in the main spec or in this change's deltas. Verify with a grep of the comments
  against the headers, showing no unmatched names.
- [ ] 2.5 Run `uv run scripts/check.py` and show that every gate passes.

## 3. Integration

- [ ] 3.1 Open the follow-up issue in `troupe-run/infrastructure` for the guard to run `openspec validate --specs
  --strict` (design, Open Questions; owner, 2026-10-23), on the roadmap board, linked from #155. Verify with
  `gh issue view <n> -R troupe-run/infrastructure --json projectItems`.
- [ ] 3.2 Push the branch, open the PR with `Closes #155`, and verify that CI passes on Linux, macOS and Windows.

## Workflow follow-up

- Archive the change on the branch with `/opsx:archive`. Then verify that `openspec validate --specs --strict`
  passes, and that each of the two requirements in the main specs has as many scenarios as on main.
- After the merge, comment on #155 with the PR and the archived change, check that it's closed, and that its card says
  Done.
