# Tasks

## 1. The nit wording (#238)

- [x] 1.1 Re-read infrastructure's `CLAUDE.md` step 5 and `openspec/config.yaml` context on `main`
  (`gh api repos/troupe-run/infrastructure/contents/<path> --jq .content | base64 -d`). Verify both still contain the
  nit sentences quoted in design, Context; if either has changed, stop and update the design before the text.
- [x] 1.2 Add the nit clause to `CLAUDE.md` step 5's must-fix sentence, as in D1, rewrapped at 120 columns. Verify
  `git diff CLAUDE.md` touches only step 5, the step still says "resolve only nits", and no new line is over 120
  columns (`awk 'length > 120' CLAUDE.md` prints only the two long-link lines it prints on `main`, step 5's last line
  and the Guardrails link, each one line later).
- [x] 1.3 Append the nit sentence to the last "Working" bullet of `openspec/config.yaml`'s context, as in D3. Verify
  `git diff openspec/config.yaml` touches only that bullet, the file still parses
  (`uv run python -c "import yaml; print(yaml.safe_load(open('openspec/config.yaml'))['schema'])"` prints
  `spec-driven`), and `openspec context --json` still resolves the root.
- [x] 1.4 Verify both files now say it: `git grep -n "nits once a push has fixed them" -- CLAUDE.md openspec/config.yaml`
  finds one line in each.
- [x] 1.5 Commit as `docs: say the review resolves a nit a push has fixed`, with `uv run scripts/check.py` passing
  first (the full check: `CLAUDE.md` is in no `scripts/check-paths.toml` group). Done as 8a0bd06; the guard's full
  check passed (3361 passed, 14 skipped).

## 2. The rest of the review's wording (#256)

- [x] 2.1 Rewrite `CLAUDE.md` step 5 to D1's text and add D2's clause to step 6, wrapped at 120 columns. Verify
  `git diff CLAUDE.md` touches only steps 5 and 6, both still read as before apart from D1 and D2 (three-OS CI,
  "Marking ready starts no review", the link, asking the owner to merge, `owner-only`), the list still reads 1 to 7,
  and `awk 'length > 120' CLAUDE.md` prints only the two long-link lines.
- [x] 2.2 Rewrite the last "Working" bullet of `openspec/config.yaml`'s context to D3's text. Verify `git diff
  openspec/config.yaml` touches only that bullet, the file parses and `openspec context --json` resolves the root (as
  in 1.3), and no line is over 120 columns.
- [x] 2.3 Verify every point is said and the stale one is gone:
  `git grep -n -E "re-run the last .claude review. run" -- CLAUDE.md openspec/config.yaml` finds nothing;
  `git grep -c -E "gets no \"fixed\"" -- CLAUDE.md openspec/config.yaml` and
  `git grep -c "claude review completed" -- CLAUDE.md openspec/config.yaml` find each file;
  `git grep -n "judg" -- openspec/config.yaml` finds the reply sentence; and `CLAUDE.md` step 6 names
  `claude review completed`, matching `gh api repos/troupe-run/troupe/rules/branches/main`'s required checks.
- [ ] 2.4 Commit as `docs: say the rest of what infrastructure says about the review`, with `uv run scripts/check.py`
  passing first (the guard runs the full check).

## 3. The pull request

- [ ] 3.1 Before opening it, re-read infrastructure's `CLAUDE.md` steps 5 and 6 and `openspec/config.yaml` context on
  `main`. Verify they still match design, Context; if not, stop and update D1 to D3.
- [ ] 3.2 Open a draft pull request with `Closes #238` and `Closes #256`, each on its own line, linking
  troupe-run/website#89 and #101. Verify `gh pr view --json closingIssuesReferences` lists both.

## Workflow follow-up

- Act on Claude's review of the last push, mark the pull request ready once it's clean (the required
  `claude review completed` check passed), and run `/opsx:archive` on the branch. The change sets `skip_specs: true`,
  so archiving moves it without touching `openspec/specs/`.
- Once every check passes and every conversation is resolved, ask the owner to merge.
- After the merge: check #238 and #256 are closed and their cards on the troupe roadmap board say Done, and comment on
  each with the PR and the archived change.
