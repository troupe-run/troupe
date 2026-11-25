# Tasks

## 1. troupe.cli.runtimes (#521)

- [ ] 1.1 Add `tests/unit/test_cli_runtimes.py`: exact lines for a resolved runtime (endpoint or in-process, model or
  how to set one, credential named or by variable, set or not, engine, price, indent) and `price_text`'s wording.
  Verify the file passes and each test fails against a hand-broken copy of the line it names (scratch edit, reverted)

## 2. troupe.cli.render (#520)

- [ ] 2.1 Extend `tests/unit/test_cli_render.py` with exact-text tests for each event type's line, the first-line cut,
  context counts, errors and notices, the run summary's optional lines, the audit, worktree changes and the list line.
  Verify the file passes

## 3. Measurement

- [ ] 3.1 With the check slot held, run mutmut 3.8.1 locally on the unit tests only, scoped to the two modules, at most
  2 children, with `scripts/mutation.json`'s settings. Verify each module scores over 60%, and record the scores and
  the survivors left (with why each is equivalent or out of reach) in the PR
- [ ] 3.2 `uv run scripts/check.py` passes before each commit

## Workflow follow-up

- Draft PR closing #520 and #521; CI's mutation-pr report confirms the scores; act on the review; archive on the
  branch before merge.
