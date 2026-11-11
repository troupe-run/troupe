# Tasks

## 1. The test tolerates a slow runner's workspace.waiting

- [ ] 1.1 Add `apart_from_waits(named)` to `test_run_notices.py`, dropping `notice workspace.waiting` entries and keeping every other entry's place, with a test that pins it on a hand-built shape. Verify that test passes.
- [ ] 1.2 Make `test_a_notice_raised_before_the_start_is_recorded_straight_after_it` assert `apart_from_waits(shape(...))[:3] == ["Started", "notice workspace.uncommitted-unseen", "WorktreeMade"]`, and run it for a quick worktree and a slow one (`WORKSPACE_ANNOUNCE_AFTER_SECONDS` patched to 0, so `workspace.waiting` is raised before the worktree, as on #380's runners). Verify the slow case fails on today's assertion and passes on the new one, and that the whole file passes.
- [ ] 1.3 Commit with `uv run scripts/check.py` passing.

## 2. Pull request

- [ ] 2.1 Open a draft pull request that closes #380, act on Claude's review of the last push, and mark it ready once it's clean. Verify every CI leg passes, Windows included.

## Workflow follow-up

- Run `/opsx:archive` on the branch before the merge.
- Ask the owner to merge. After the merge, check #380 is closed and its card says Done, and comment with the PR and the archived change.
