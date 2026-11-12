# Tasks

Every commit is signed and signed off (`git commit -S -s`), and `uv run scripts/check.py` passes before it.

## 1. Compaction off in the runner's settings file

- [x] 1.1 In `command.py`'s `build()`, add `"autoCompactEnabled": False` to the settings file, with a comment citing
  #279 point 3 and design D1. Add tests in `test_claude_code_command.py`: one whose name says the settings file holds
  `autoCompactEnabled` false for a run with no options, and one for `settingSources` `["project"]`. Verify both fail
  before the change and pass after it.
- [x] 1.2 README (`plugins/runner-claude-code/README.md`): under "What it runs", say the settings file turns off
  Claude Code's automatic compaction, and why a loaded setting source can't turn it back on. Under "How a run ends",
  say a run whose context fills ends `error` with `context-length`, that a long run which compacted before now fails,
  and the way out (split the task; opt in once #310 lands). Verify `test_claude_code_readme.py` passes.
- [ ] 1.3 Commit as `feat(claude-code)!: turn off Claude Code's automatic compaction` with a `BREAKING CHANGE:`
  footer naming the behaviour change, after `uv run scripts/check.py` passes.

## 2. The context limit maps to context-length

- [ ] 2.1 In `mapping.py`, add a `TERMINAL_REASONS` table (`prompt_too_long` and `blocking_limit` to
  `context-length`) and check it first in `_failure_reason` for an `is_error` result under subtype `success`
  (design D2). Add tests in `test_claude_code_mapping.py` for each value, for a context limit after a rate-limit retry
  (the spec's scenario), and that a successful result with `terminal_reason` `prompt_too_long` stays `ok`. Verify the
  existing reason tests still pass unchanged.
- [ ] 2.2 Update the `result` row of the Claude Code mapping in `contributing/runners.md`: `terminal_reason`
  `prompt_too_long` or `blocking_limit` gives `context-length`, before the error code, the retry and the status.
  Verify the docs link checks in `scripts/check.py` pass.

## 3. Context-limit fixtures, captured offline

- [ ] 3.1 Extend `tools/capture_claude.py` (design D3): a stand-in API that streams one `Read` tool call with a given
  `input_tokens` and refuses any later request with the API's 400 `invalid_request_error` "prompt is too long"; the
  fixtures `context-limit-refused` (185,000 tokens) and `context-limit-blocked` (990,000 tokens), launched through the
  runner's `build()`; and a refusal to write the fixture when the output holds `system/status` `compacting` or the
  stand-in saw more requests than the case expects. Document both in the module docstring. Verify by running the
  tool for both fixtures and checking it writes them, and by running it once with the setting taken out of a local
  copy of the launch, checking it refuses (not committed).
- [ ] 3.2 Write each fixture's `expected.json` (outcome `failed`, `run.error-result`, exit code 1) and the paired
  events by hand from the native lines, following the updated mapping, ending in a `result` with `reason`
  `context-length`. Verify `test_claude_code_fixtures.py` (mapping, provenance, secret scan) passes with both, and
  that `packages/troupe/tests/test_claude_code_host.py` replays both through the host.
- [ ] 3.3 Add the two fixtures to the README's fixture list, and to the fixture names `test_claude_code_fixtures.py`
  lists explicitly, if it lists them. Run the full `uv run scripts/check.py`, keeping its log in a scratch file, and
  commit.

## 4. User docs

- [ ] 4.1 In `docs/opening-night/first-performance.md` (the list of what a Claude Code run does) and
  `docs/stagecraft/bring-your-own-agent.md` (the Claude Code runner's line), say that Claude Code doesn't compact a
  run's conversation: a run that fills its context fails with a conversation too long for the model, and a long task
  is split, until actors can opt in (#310). Verify the user-docs checks (front matter, links, glossary) pass, and
  commit.

## 5. Optional: a real-API confirmation, by the owner

- [ ] 5.1 Owner only, never in an agent session, not blocking the PR (design D4): run Claude Code as the runner
  launches it with a real credential, `claude-haiku-5-5` and `--max-budget-usd 2`, with a direction that reads enough
  workspace files to pass the window, and check its result record has `terminal_reason` `prompt_too_long` or
  `blocking_limit`, no `system/status` `compacting`, and that the runner maps it to `context-length`. Record the
  outcome on #308. If the owner skips it, leave this unticked and say so in the PR.

## Workflow follow-up

- Open a draft PR that closes #308, act on Claude's review of the last push, then mark it ready.
- Archive the change on the branch before merging; the owner merges through the merge queue.
- After the merge, comment on #308 with the PR and the archived change, check #308 is closed and its card is Done,
  and tell the #310 session that it's unblocked.
