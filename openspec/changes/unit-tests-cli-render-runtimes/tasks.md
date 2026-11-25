# Tasks

## 1. troupe.cli.runtimes (#521)

- [x] 1.1 Add `tests/unit/test_cli_runtimes.py`: exact lines for a resolved runtime (endpoint or in-process, model or
  how to set one, credential named or by variable, set or not, engine, price, indent) and `price_text`'s wording.
  Verify the file passes; that each test fails when the text it pins changes is what the mutation run in 3.1 checks

## 2. troupe.cli.render (#520)

- [x] 2.1 Extend `tests/unit/test_cli_render.py` with exact-text tests for each event type's line, the first-line cut,
  context counts, errors and notices; add `tests/unit/test_cli_render_summary.py` for the run summary's optional
  lines, the audit, worktree changes and the list line. Verify both files pass

## 3. Measurement

- [x] 3.1 With the check slot held, run mutmut 3.8.1 locally on the unit tests only, scoped to the two modules, at most
  2 children, with `scripts/mutation.json`'s settings. Verify each module scores over 60%, and record the scores and
  the survivors left (with why each is equivalent or out of reach) in the PR. Measured 2026-11-26 (the per-mutant
  memory cap nulled in the throwaway clone only: macOS refuses `RLIMIT_AS`, which would count every mutant caught):
  `troupe.cli.runtimes` 110 of 110 killed (100%), `troupe.cli.render` 736 of 755 killed (97.5%). The 19 left are
  equivalent: 18 are the `''` default of a field the event's protocol type requires (`text`, `inputSummary`,
  `outputSummary`, `message`), and one passes `short=None` where `False` is meant, which reads the same
- [x] 3.2 `uv run scripts/check.py` passes before each commit (7811 passed, 20 skipped; all gates passed)

## Workflow follow-up

- Draft PR closing #520 and #521; CI's mutation-pr report confirms the scores; act on the review; archive on the
  branch before merge.
