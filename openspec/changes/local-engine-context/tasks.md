# Tasks

## 1. Fail first

- [ ] 1.1 Add the derived fixture `lm-studio-conversation-cut-cached` (design D6): replies 0, 1 and 4 of
  `lm-studio-conversation-cut`, provenance saying it's derived from them and why, `options.engine` `lm-studio`, and
  its expected events ending `context-length` after two requests' tool calls, with nothing from the third reply. Verify:
  its replay test fails on main's code (the runner acts on reply 4 and sends a fourth request), seen before any code
  change.
- [ ] 1.2 Add tests for the usage scenarios ("LM Studio's cache reads counted once", "The same replies with the engine
  unknown"), the guard scenarios (cut with cache reads, named and unknown; Claude's cache reads rising) and the window
  scenario (LM Studio's cache reads don't fill it). Verify: the LM Studio and unknown-engine ones fail on main, and the
  Claude one passes on main (the property that must stay the same).

## 2. The engine (design D1, D2)

- [ ] 2.1 Add `Engine` and `ENGINES` to `context.py`, each entry pinned. Verify: a table test checks the four engines,
  their accounting, a pin for each, and that every `Signal.engine` names an entry.
- [ ] 2.2 Add the `engine` option to `options.py` and `schemas/options.schema.json` (closed enum), and resolve the
  run's engine: the option, else `claude` for an `https://api.anthropic.com` endpoint, else unknown. Verify: the options
  tests refuse `lmstudio` and `LM Studio` with `anthropic.invalid-options` naming `options.engine`, the schema-versus-
  code property test passes with the new option, and a test resolves each of the three cases.
  If the owner picks option B or C (D2), this task moves to where the engine comes from instead.

## 3. Counting and guarding per engine (design D3, D4, D5)

- [ ] 3.1 Add `prompt_readings` and change `shrank` to compare readings (D3). Replace `Reply.prompt_tokens` uses in the
  guards and the estimate with it. Verify: the context unit tests and property tests (a growing conversation never
  shrinks under any engine; a drop in any reading is caught when unknown) pass.
- [ ] 3.2 Count usage per engine in `_Spend.add` (D4). Verify: the usage tests from 1.2 pass, and so does the budget test
  on corrected counts.
- [ ] 3.3 Send the one-time warning (D5). Verify: tests for one warning on cache reads with the engine unknown, none
  without cache reads, and none with the engine named.
- [ ] 3.4 Name the engine in every fixture's provenance and update the LM Studio fixtures' expected usage (D6). Verify:
  a test checks each fixture names an engine from the table, and every fixture replays, 1.1's included.

## 4. Docs

- [ ] 4.1 README: the `engine` option in the options table; usage per engine, replacing the #419 note; The context, now
  saying the prompt is measured per engine and conservatively when unknown, and listing which engines can still lose
  content silently (Ollama's first request; an unnamed engine as far as both readings allow). Verify: the README test
  passes, and the README names each engine in `ENGINES`.
- [ ] 4.2 Check the other pages that describe this runner's options or usage (`docs/`, `contributing/runners.md`) and
  update any that list its options. Verify: `grep -rn contextWindow docs contributing` shows each listing also names
  `engine`, or isn't a listing.

## 5. Verify the whole change

- [ ] 5.1 Run `uv run scripts/check.py` when the load is under 40, its output kept in a scratch file. Verify: it passes,
  and its summary line goes in the pull request.
- [ ] 5.2 Open the pull request as a draft (`Closes #418`, `Closes #419`), act on the review of the last push, and mark
  it ready once it's clean. Verify: `gh pr checks` shows every job passing on the head, on Linux, macOS and Windows.

## Workflow follow-up

- Archive on the branch after the review is acted on, before the owner merges.
- After the merge, check #418 and #419 are closed and their cards say Done, and comment on each with the PR and the
  archived change.
