# Tasks

## 1. Remove troupe's copy

- [ ] 1.1 Delete `scripts/tests/test_guard_*.py` and `docs/development-workflow.md`. Verify: `uv run scripts/check.py`
  passes, and `test_check_activation.py` still runs.
- [ ] 1.2 Point `CLAUDE.md`, `README.md` and `scripts/check.py`'s docstring at
  `troupe-run/infrastructure`'s rules doc and spec. Verify: `grep -rn "docs/development-workflow.md"` outside
  `openspec/changes/archive/` finds only links to infrastructure.
- [ ] 1.3 Archive on the branch, which retires `openspec/specs/development-workflow`. Verify: the main spec is gone,
  and `openspec validate --specs` passes.

## 2. Pull request

- [ ] 2.1 Open the PR closing #30. Verify: CI on all three platforms, `guard` and DCO are green.

## Workflow follow-up

- The owner merges by rebase. Then troupe-run/infrastructure delivers the guard (infrastructure#8, task 6).
- Comment on #30 with the PR and the archived change.
