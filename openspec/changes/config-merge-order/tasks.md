# Tasks

## 1. Pin what must not change, and the failures (before any code)

- [x] 1.1 On this branch, before changing `merge.py`, time and run the existing merge tests: `test_config_merge.py`,
  `test_config_merge_files.py`, `test_cli_config_merges.py` and `test_config_merge_properties.py`. Record the times
  (the properties' "passed in" line) for design D3's comparison. Verify they pass on the unchanged code.
- [x] 1.2 Add an "every order that keeps parents before children" helper to `test_config_merge_properties.py`, and
  #190's history as a plain test built with `_changed` and `_settled` from the saved example's versions and entries
  (design D3). Check that the ids match the saved example's. It checks that every order (12) gives `reviewer.expect ==
  ["a.txt"]`, one conflict at `actors.reviewer.expect` naming versions 14 and 15, and heads 14 and 15. Verify it fails
  on the unchanged code, with the two values the issue reports.
- [x] 1.3 Add the spec delta's two scenarios as records-level tests next to it, through every order: a conflict
  after a settle shows the value the settle left, and lines after a settle that each change `tester`'s character and
  change it back leave the value the settle left, with no conflict. Verify both fail on the unchanged code (6 and 18
  orders, two results each).
- [x] 1.4 Add the same two scenarios to `test_config_merge.py` under "Requirement: A merge combines each line's net
  change", through a real store and git branches: two branches set `tester`'s character, one to new text and the
  other to other text and back; they're merged and a `config set` of another value settles them; two branches from
  there then set the character differently (or each change it and back). Each checks the value and conflicts from
  `config_of`. Run them on the unchanged code and record whether they fail: the store's order on one clone may happen
  to give the right value, and the records-level tests in 1.3 are the ones that cover every order. Each test's name
  states only what its body checks.

## 2. The fix (design D1, D2)

- [x] 2.1 In `_contest`, after the first round, loop as design D1 says: while no latest write's line stays in,
  contest the covering writes not yet left out, recomputing the latest among them, and add what each round leaves
  out. Report only the first round's conflict (D2). Keep `merge`, `apply_in_order`, `_grouped` and `_invalid` as they
  are. Verify 1.2 and 1.3 pass, 1.4 passes, and every test from 1.1 still passes unchanged. mypy --strict and ruff
  pass.
- [x] 2.2 Rewrite the module docstring's "Replay" paragraph to say that where nothing at a point's frontier stays in,
  the writes beneath are contested by the same rule, so concurrent writes left in never overlap. Change the "Replay"
  bullet in `contributing/config.md`, "The merge", to match. Verify with the docs tests (`uv run scripts/check.py`'s
  docs step) and by reading both against design D1.
- [x] 2.3 Replay the saved example: copy `.hypothesis/` from the `troupe-188-release-config-tests` worktree into a
  scratch directory (never change that worktree's copy) and run the order property from there against this branch.
  Verify it passes.

## 3. The property's reach (design D3, risks)

- [x] 3.1 Raise the order property's `max_examples` from 150 to 500. Time both properties against 1.1's numbers, and
  keep a lower count if the increase is more than a few seconds, saying why in the commit. Verify the property passes.
- [ ] 3.2 Run both properties over at least 100 seeds (`--hypothesis-seed=1..100`), keeping the output in the
  scratchpad. Ask the owner before starting it, since it runs for several minutes (memory: ask before load-heavy local
  runs). Verify every seed passes. Any failure is captured whole, becomes an explicit test like 1.2, and is fixed
  before this task is ticked.

## 4. Lines whose first writes disagree (design D4, found by 3.2)

- [x] 4.1 Add seed 31's history as a plain test next to #190's, built with `_step` and `_settled` (its ids match the
  seed's), through every order (14): it checks that each order gives one conflict at `actors.tester.character`
  naming versions 10 and 14, and the same config. Add the spec delta's third scenario through a real store and git
  in `test_config_merge.py`. Verify both fail on the unchanged rule.
- [x] 4.2 Make a line drop out only when every first write's `before` is the value it ends at (design D4). Verify
  4.1's tests pass, every test from 1.1 and group 1 still passes, and mypy --strict and ruff pass. Add the rule to
  the module docstring's "A line's net change" paragraph and to `contributing/config.md`, "The merge", and verify
  with the docs tests.
- [ ] 4.3 Run both properties over seeds 1 to 100 again, output kept in the scratchpad. Verify every seed passes.

## 5. Integration

- [ ] 5.1 Run `uv run scripts/check.py`. Verify it passes.

## Workflow follow-up

- Open the pull request with `Closes #190`, and say in it that #188 rebases onto it once it merges.
- Act on Claude's review of the last push, then archive the change on the branch before merging.
- After the merge: comment on #190 with the PR and the archived change, check #190 is closed and its card is Done,
  and tell the #188 session it can rebase.
