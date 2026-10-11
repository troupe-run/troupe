# Design

## Context

See proposal.md for why. What shapes the approach:

- The repo (`R_kgDOVEZa3g`) is public, and `troupe-run/troupe` is free (`gh api repos/troupe-run/troupe` → 404).
- In this repo, `git grep "troupe\.run"` outside the archive finds 11 lines. Six name the repo and change, three name the
  domain and stay, and `CLAUDE.md`'s title names the repo.
- The website clone has 16 lines naming the repo, which matches the issue's count: the copy (header, hero, closing), two docs
  pages, the e2e test, the weekly link-check workflow, CONTRIBUTING, and the site's design spec and build plan under
  `docs/superpowers/`.
- The org profile (`troupe-run/.github`, `profile/README.md:11`) links the repo. The `infrastructure` repo has no
  reference yet.
- Open issues that name the repo: #19, #25 and #26.
- The DCO app (installation `170159387`) and `troupe-run-infrastructure` (`170224209`) are installed on *selected*
  repos. GitHub keeps a selected repo by ID, so a rename shouldn't affect either.
- Path-bound local state, all keyed by `/Users/martin/Projects/troupe/troupe.run` (Claude Code here runs with
  `CLAUDE_CONFIG_DIR=~/.claude-troupe`):
  - `~/.claude-troupe/projects/-Users-martin-Projects-troupe-troupe-run/`: session transcripts and `memory/`;
  - the `projects["/Users/martin/Projects/troupe/troupe.run"]` entry in `~/.claude-troupe/.claude.json`: trust,
    allowed tools, MCP choices;
  - 88 entries in `~/.claude-troupe/history.jsonl` whose `project` is the old path (prompt history);
  - `.venv/`: uv writes absolute shebangs (`#!/Users/martin/Projects/troupe/troupe.run/.venv/bin/python`).
  - `core.hooksPath` is relative (`.githooks`) and there are no extra worktrees, so neither needs anything.

## Goals / Non-Goals

**Goals:**
- After the change, nothing live (code, docs, sites, issue bodies, the workspace) names `troupe-run/troupe.run` or
  relies on a redirect from it.
- The renamed folder opens in Claude Code with its memory, history and settings intact, as if it had always been
  called `troupe`.

**Non-Goals:**
- Rewriting history: archived changes, commit messages, closed issues and PR bodies keep the old name.
- A reusable "rename a repo" tool. This is a one-off; the commands live in tasks.md.

## Decisions

### 1. Rename on GitHub after the code is committed, immediately before the PR

The branch is built and checked first. Only then is the repo renamed (`gh repo rename troupe --repo
troupe-run/troupe.run`), the remote set, and the PR opened, as the issue asks. That way the PR's new URLs resolve from
the moment it exists, and the window where the repo has the new name but `main` still says the old one is as short
as possible. The alternative, renaming first, leaves `main` naming a repo that no longer exists for the whole
implementation. The rename is outward-facing, so the owner confirms it at that step.

### 2. The guard-test fixture uses a genuinely different repo

`test_a_pr_body_referring_to_another_repository_s_issue_is_allowed` uses `troupe-run/troupe.run#22`, which is *this*
repo, so its name claims more than its fixture shows. Swapping in `troupe-run/troupe#22` would keep that flaw.
Instead it uses `troupe-run/infrastructure#1`, an issue reference in a repo that really is different, so the name and the body agree. The number is illustrative: the guard parses the reference without calling GitHub, and no other org repo has an issue yet.

### 3. The website's 16 references all change, the design records included

The issue counts 16, and that count includes `docs/superpowers/` (the site's design spec and build plan). Unlike
archived OpenSpec changes, the design spec is the site's living design record: its "the repo must exist and be
public" precondition still matters, and it should name the real repo. The plan is updated along with it so the two
don't disagree. The link checker's `--skip github.com/troupe-run/troupe.run` is renamed, not removed. Whether to stop
skipping GitHub at all is a separate decision about the site.

### 4. The org profile is updated too, in its own PR

It isn't in the issue's list, but it is a live reference, and leaving it contradicts the outcome. It is a one-line PR
to `troupe-run/.github` that cites #26, with the link text changed from "troupe.run repository" to "troupe
repository".

### 5. The local move happens from outside the folder, before the archive

A running session's working directory can't be renamed from under it. Once the PR is green, the owner ends the
session and does the move in a terminal opened in `~/Projects/troupe/`, with no session open in the clone. A new
Claude Code session in `~/Projects/troupe/troupe` then checks the move, ticks it, and archives and merges. Doing the
move before the archive keeps it a tracked task, checked from the renamed folder itself. It
moves the folder and the Claude project directory with `mv` (no copy, so nothing exists twice). It rewrites the
`.claude.json` key and the `history.jsonl` `project` fields with a short Python script that backs up both files
first. It rebuilds `.venv` with `uv sync`. Leaving the old Claude state behind would be harmless, but Claude Code would
treat the new folder as a stranger, with no memory, no trust and no history. That is the data loss to avoid.

### 6. The memory's text is updated as well as its location

`troupe-decisions-live-in-github-issues.md` and `MEMORY.md` say "in troupe-run/troupe.run". Moving the directory
keeps them loadable. Editing the text keeps them true.

## Risks / Trade-offs

- [The rename lands but the PR is delayed] → `main` names the old repo, and GitHub's redirect covers it. Keep the gap
  short: rename, push, PR in one sitting.
- [Something unexpected still uses the old name] → Before the PR, `git grep -n "troupe-run/troupe\.run"` outside the
  archive must return nothing. After the PR, the same grep runs across the website and `.github` clones.
- [An App silently loses the repo] → Check each installation's repository list by ID after the rename (`gh api
  user/installations/<id>/repositories`). Then confirm DCO really runs: its check must appear on this PR.
- [The local move half-completes] → Back up `.claude.json` and `history.jsonl` before rewriting them. Use `mv`, which
  is atomic on one volume. Rollback is the reverse `mv` and restoring the backups.
- [Something else keys on the folder path] → After the move, start Claude Code in the new folder, check that the
  memory index loads and earlier sessions show in `/resume`, then run `uv run scripts/check.py`.

## Migration Plan

1. Branch: code and docs changes, `scripts/check.py` green, committed.
2. GitHub: rename the repo (owner confirms), `git remote set-url origin git@github.com:troupe-run/troupe.git`, confirm
   the new URLs resolve, push, open the PR (`Closes #26`), and confirm the Apps cover it.
3. Org: website PR and `.github` PR, each citing #26. Edit the #19 and #25 bodies.
4. Local move, from `~/Projects/troupe/`, with no session open in the clone. Then a new session in the renamed folder
   checks it.
5. Archive on the branch, merge, comment on #26.

Rollback: GitHub allows renaming back. Until something else claims `troupe-run/troupe.run`, its redirects keep
working in both directions.
