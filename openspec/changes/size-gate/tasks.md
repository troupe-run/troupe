# Tasks

## 1. Declare the size gate (D1, D2)

- [x] 1.1 Add `[size]` and `[size.allow]` to `quality-gates.toml` with D1's limits and exclusions and D2's seven
  ceilings, each with its split issue. Verify: `uv run scripts/quality_gates.py size` passes on this branch, and
  `uv run scripts/quality_gates.py size --base <root commit>` (every file treated as new) fails on no file but ones
  over 48 KiB with no entry (none expected outside the exclusions).
- [x] 1.2 Mutation checks on the declaration. Verify each fails the gate as the spec says, then revert: append 20 KiB
  to a file with no entry (`openspec/specs/runs/spec.md`); lower one ceiling below its file's size; add an entry for
  a file under 48 KiB.

## 2. Run it on every check (D3)

- [x] 2.1 Add the `size` step after `complexity` in `scripts/check.py`'s `gates()`, passing `--base` as complexity
  does, and say so in the module docstring. Update `test_check_gates.py` (size runs locally, scoped and on the leg,
  before the tests, with the base) and `test_check_scope.py`'s full list. Verify: the tests fail before the
  `check.py` edit and pass after it.

## 3. Drop the hand-written delivered-file patterns (D4)

- [x] 3.1 Remove the delivered-file patterns from `[complexity] exclude` and `[tool.coverage.run] omit`, and reword
  their comments to say the delivery list leaves them out. Verify: with every delivered `.py` file touched (a comment
  line appended to each, plus 60 KiB appended to `scripts/guard.py`), `quality_gates.py complexity` and `size`
  judge none of them; revert.
- [x] 3.2 Verify coverage leaves them out too: run the tests for `scripts` under coverage locally into a scratch
  report and run `quality_gates.py coverage --coveragepy <report>` against it (outside the leg variable), and check
  no delivered file is reported and no file is "in no package".

## 4. Document it

- [x] 4.1 `contributing/quality-gates.md`: the size gate's row in the table, a section with its failure, its note and
  what to do (split, or a ceiling with a split issue), and "Left out" saying delivered files are left out by the
  delivery list. Verify: the docs tests pass.

## 5. Check

- [ ] 5.1 One full `uv run scripts/check.py` (heavy-run slot from the orchestrator), output kept in a scratch file.
  Verify: it passes, printing the size step's line.
