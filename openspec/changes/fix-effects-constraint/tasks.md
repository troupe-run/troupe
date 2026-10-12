# Tasks

## 1. Reword

- [ ] 1.1 In `openspec/config.yaml`, replace the pluggable-extensions line with the proposal's wording; verify `git diff openspec/config.yaml` changes only that line's block, the file parses (`uv run --with pyyaml python -c "import yaml;yaml.safe_load(open('openspec/config.yaml'))"`), and `openspec instructions proposal --change fix-effects-constraint --json` returns the new text and no longer contains "enforced on code that runs over JSON-RPC"
- [ ] 1.2 In `plugins/README.md`, replace the opening paragraph with the proposal's wording, linking #3 and #37; verify the rest of the file is unchanged (`git diff --stat`), and `git grep -n -i "can be enforced on them\|enforced on code that runs over" -- . ':!openspec/changes'` returns nothing

## 2. Check

- [ ] 2.1 Run `uv run scripts/check.py`, and verify all gates pass

## Workflow follow-up

- Open the PR with `Closes #46`; CI must pass on Linux, macOS and Windows.
- Archive the change on the branch (`/opsx:archive`) before merging. There are no delta specs to sync.
- After the merge, comment on #46 with the PR and the archived change.
