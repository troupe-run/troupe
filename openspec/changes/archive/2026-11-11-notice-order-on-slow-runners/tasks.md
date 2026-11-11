# Tasks

## 1. The test tolerates a slow runner's workspace.waiting

- [x] 1.1 Add `apart_from_waits(named)` to `test_run_notices.py`, dropping `notice workspace.waiting` entries and keeping every other entry's place. It's pinned on a real run by 1.2's slow case, which checks a `workspace.waiting` was recorded before the worktree and that the rest keep their order. Verify by 1.2.
- [x] 1.2 Make `test_a_notice_raised_before_the_start_is_recorded_straight_after_it` assert `apart_from_waits(shape(...))[:3] == ["Started", "notice workspace.uncommitted-unseen", "WorktreeMade"]`, and run it for a quick worktree and a slow one (`workspaces.announced` replaced by `announced_at_once`, which raises `workspace.waiting` as each operation starts, as #380's runners did after 2 s; patching `WORKSPACE_ANNOUNCE_AFTER_SECONDS` to 0 instead would leave a timer a quick operation can still cancel before it fires). Verify the slow case fails on today's assertion and passes on the new one, and that the whole file passes.
- [x] 1.3 Commit with `uv run scripts/check.py` passing.

## 2. Pull request

- [x] 2.1 Open a draft pull request that closes #380, act on Claude's review of the last push, and mark it ready once it's clean. Verify every CI leg passes, Windows included.

## Workflow follow-up

- Run `/opsx:archive` on the branch before the merge.
- Ask the owner to merge. After the merge, check #380 is closed and its card says Done, and comment with the PR and the archived change.
