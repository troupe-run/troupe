# Tasks

## 1. The project context

- [ ] 1.1 In `openspec/config.yaml`, replace "Third-party code only ever runs out of process", the pluggable-extensions line, the repo-layout line and the lineage line with design D1's wording, and add the malformed-input rule after "Refuse rather than guess"; verify `git diff openspec/config.yaml` touches only those five lines' blocks, `python -c "import yaml;yaml.safe_load(open('openspec/config.yaml'))"` (via `uv run`) parses it, and `openspec instructions proposal --change update-project-constraints --json` returns the new text in its `context`
- [ ] 1.2 Verify nothing else still states the old rule: `git grep -n -i "third-party code only" -- . ':!openspec/changes'` returns nothing, apart from `plugins/README.md` (task 2.1)

## 2. The plugins README

- [ ] 2.1 Rewrite `plugins/README.md`'s opening paragraph and its in-process adapters paragraph with design D2's wording, leaving the rules list unchanged; verify `git grep -n -i "third-party code only" -- . ':!openspec/changes'` returns nothing, and the `#37` and `#38` links resolve (`gh issue view 37`, `gh issue view 38`)

## 3. Record and check

- [ ] 3.1 Comment on #37 with the correction from design D1 ("plugins, ours included, run over JSON-RPC"; the line is drawn at core and its bundled adapters, not at shipped versus acquired); verify the comment URL is returned
- [ ] 3.2 Run `uv run scripts/check.py`, and verify all gates pass

## Workflow follow-up

- Open the PR with `Closes #39`; CI must pass on Linux, macOS and Windows.
- Archive the change on the branch (`/opsx:archive`) before merging. There are no delta specs to sync.
- After the merge, comment on #39 with the PR and the archived change.
