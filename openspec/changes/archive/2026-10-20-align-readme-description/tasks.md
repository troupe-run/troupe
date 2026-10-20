# Tasks

## 1. The README

- [x] 1.1 Replace the paragraph under the tagline and the opening of the status paragraph with design D1's text, leaving the tagline and the rest of the README as they are; verify with `git diff README.md` that only those two paragraphs changed, and that the paragraph matches the org profile's (`gh api repos/troupe-run/infrastructure/contents/org-profile/profile/README.md --jq .content | base64 -d`) word for word

## 2. The docs page

- [x] 2.1 In `docs/programme/what-is-troupe.md`, replace the front-matter `description` and the opening line with D1's sentence; verify `uv run scripts/check.py --scope docs` passes

## 3. The package

- [x] 3.1 Replace the one-liner in `packages/troupe/pyproject.toml`'s `description`, the root parser's `description` in `packages/troupe/src/troupe/cli/parser.py` and the docstring in `packages/troupe/src/troupe/__init__.py` with D1's text; verify `uv run troupe --help` prints "Run your development process with a team of agents, asking only when it needs you." and `uv lock --check` passes

## 4. The agent-facing copies

- [x] 4.1 Replace the opening sentence of `CLAUDE.md` and of `openspec/config.yaml`'s `context` with D1's text; verify `openspec instructions proposal --change align-readme-description --json | jq -r .context | head -1` prints the new sentence, which shows the config still parses

## 5. Check

- [x] 5.1 Verify `git grep -n "named roles" -- . ':!openspec/changes'` returns nothing, and `uv run scripts/check.py` passes

## Workflow follow-up

- Open the PR with `Closes #130`, referencing troupe-run/infrastructure#108. CI must pass on Linux, macOS and Windows.
- Archive the change on the branch (`/opsx:archive`) before merging. There are no delta specs to sync.
- After the merge, check #130 is closed and its roadmap card says Done, and comment on #130 and on troupe-run/infrastructure#108 with the PR and the archived change. #108 stays open for troupe-run/website#26.
