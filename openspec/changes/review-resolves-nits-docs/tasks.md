# Tasks

## 1. The wording (#238, design D1 and D2)

- [x] 1.1 Re-read infrastructure's `CLAUDE.md` step 5 and `openspec/config.yaml` context on `main`
  (`gh api repos/troupe-run/infrastructure/contents/<path> --jq .content | base64 -d`). Verify both still contain the
  sentences quoted in design, Context; if either has changed, stop and update D1 and D2 before the text.
- [ ] 1.2 Replace the middle sentence of `CLAUDE.md` step 5 with D1's text, rewrapped at 120 columns. Verify
  `git diff CLAUDE.md` touches only step 5, the step still says "resolve only nits", and no line is over 120 columns
  (`awk 'length > 120' CLAUDE.md` prints nothing).
- [ ] 1.3 Append D2's sentence to the last "Working" bullet of `openspec/config.yaml`'s context. Verify
  `git diff openspec/config.yaml` touches only that bullet, the file still parses
  (`uv run python -c "import yaml; print(yaml.safe_load(open('openspec/config.yaml'))['schema'])"` prints
  `spec-driven`), and `openspec context --json` still resolves the root.
- [ ] 1.4 Verify both files now say it: `git grep -n "nits once a push has fixed them" -- CLAUDE.md openspec/config.yaml`
  finds one line in each.
- [ ] 1.5 Commit as `docs: say the review resolves a nit a push has fixed`, with `uv run scripts/check.py` passing
  first (the full check: `CLAUDE.md` is in no `scripts/check-paths.toml` group).

## 2. The pull request

- [ ] 2.1 Open a draft pull request with `Closes #238` on its own line, saying the remaining differences are #256
  (not closed by it). Verify `gh pr view --json closingIssuesReferences` lists #238.

## Workflow follow-up

- Act on Claude's review of the last push, mark the pull request ready once it's clean, and run `/opsx:archive` on
  the branch. The change sets `skip_specs: true`, so archiving moves it without touching `openspec/specs/`.
- Once every check passes and every conversation is resolved, ask the owner to merge.
- After the merge: check #238 is closed and its card on the troupe roadmap board says Done, and comment on it with
  the PR and the archived change.
