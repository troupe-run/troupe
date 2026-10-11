# Design

## Context

`pr_closes_issue` in `scripts/guard.py` is called by `shell_decisions(command, cwd)` for each simple command in a
Bash tool call. It already parses `gh pr create`'s flags (`--body`, `--body-file`, `--fill`) but ignores the target.
The PreToolUse hook resolves `root` from the session's working directory before calling `shell_decisions`, and
`git(root, ...)` runs git with hook-time variables stripped. See proposal.md for why the rule should be scoped.

## Goals / Non-Goals

**Goals:**
- A PR the agent explicitly opens into another repository is never refused by this rule.
- No PR into this repository gets past the rule because its target was misread.

**Non-Goals:**
- Replicating `gh`'s own default-repository resolution (`gh repo set-default`, the order it tries remotes in, the
  working directory after a `cd` earlier in the same command line).
- Checking PR descriptions anywhere but in a Claude Code session. The git hooks and the GitHub `guard` check don't
  look at descriptions today, and this change doesn't add that.

## Decisions

1. **The target comes only from what the command says.** `-R`/`--repo` (both `--repo x` and `--repo=x`) wins.
   Otherwise `GH_REPO`, read from a leading `GH_REPO=...` assignment on the command, then from the hook's environment
   (which the command inherits). With neither, the target is this repository.
   *Alternative:* follow `gh`'s default resolution from the working directory. Rejected: it depends on `gh`'s
   config and on the shell's directory after earlier `cd`s, which the hook can't see. Every case it would rescue is
   one where the agent can say `--repo` explicitly, and getting it wrong lets a PR into this repo through.

2. **"This repository" is any remote of the clone the hook resolved (`root`).** The remotes are read with
   `git remote -v` only when the rule meets a `gh pr create` that names a target, so ordinary commands pay nothing.
   A target matching any of them is this repository. In a fork's clone, `origin` is the fork and `upstream` is
   troupe, so a PR into either is checked. A PR into the website or `.github` matches neither.
   *Alternatives:* `origin` alone. Rejected: in a fork's clone, `--repo troupe-run/troupe` wouldn't match the fork's
   origin and would go unchecked. A hard-coded `troupe-run/troupe`. Rejected: the repo was just renamed, and a
   constant would have needed changing with it, while the remotes already moved (task 1.4 of rename-repo).

3. **Repository names are normalised to `(host, owner, name)`, lower-cased.** Accepted forms are the ones `gh`
   accepts for `--repo`: `OWNER/REPO`, `HOST/OWNER/REPO` and an `https://` URL. A remote URL may also be
   `git@HOST:OWNER/REPO` or `ssh://git@HOST/OWNER/REPO`. A trailing `.git` and `/` are dropped. A name without a host
   means `github.com`. Two repos are the same only when all three parts match.

4. **Anything unrecognised counts as this repository.** That covers a `--repo` value that doesn't normalise, no
   remotes at all, or a git failure. A remote URL that doesn't normalise is skipped, since it can't name a target.
   These cases are rare and need no new message: the existing refusal's fix (add `Closes #<issue>`) is still right
   for this repo, and the agent can name the other repo explicitly. This follows "refuse rather than guess", and its error is the one that can't let a PR into this repo
   through.

5. **No change to the refusal's text.** A refused PR is, by construction, one into this repository, so the existing
   problem and fix still read correctly.

## Risks / Trade-offs

- [`gh repo set-default` points at another repo, with no `--repo`] → The PR is checked as if into this repo, the
  same as today. The agent can pass `--repo` to make the target explicit.
- [`cd ../site && gh pr create ...` in one Bash call] → Checked as this repo, the same as today. The fix is the same:
  `--repo`.
- [A clone with a remote for an unrelated repo, such as the website added as a second remote] → PRs into that repo
  are checked too, as now. The agent can add `Closes` or the owner can override. Rare, and on the side of checking.
- [A remote added mid-session] → Read fresh on each `gh pr create`, so it counts at once.
