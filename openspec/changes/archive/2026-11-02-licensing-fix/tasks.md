# Tasks

## 1. The licensing page points to the install page

- [x] 1.1 In `docs/backstage/licensing.md`, replace "There's nothing to install yet." with "You can install it from a
  release ([Install](../opening-night/install.md))." Leave the rest of the page and its front matter alone. Verify
  `git diff --stat` shows only this file, and that `grep -rni "nothing to install" README.md docs packages/*/README.md`
  finds nothing.
- [x] 1.2 Verify the link resolves:
  `uv run pytest packages/troupe/tests/test_user_docs_links.py` passes.
- [x] 1.3 Run `uv run scripts/check.py` and verify it passes.
  - 2026-11-02, macOS: all gates passed, 3361 passed and 14 skipped (platform-only and opt-in tests).

## Workflow follow-up

- Open the draft pull request with `Closes #237`. Mention troupe-run/website#83, which waits on it.
- After the merge, comment on #237 with the pull request and the archived change, and check that its card on the
  roadmap board says Done.
