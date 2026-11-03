# Design: the first run leads with a real agent and your own prompt

## Context

See proposal.md for why. What's there now:

- `troupe init` and `troupe init --audition [--runner <runner>]` shipped in #260 (`packages/troupe/src/troupe/cli/init.py`,
  `troupe/core/audition.py`). The audition defines the actor `lead`. With Claude Code it writes
  `.troupe/actors/lead.yaml` (options: `maxBudgetUsd` 1, `acceptEdits`, Read/Write/Edit/Glob/Grep; `expect: []`) and
  `.troupe/actors/lead.md` (its character). With `--runner scripted` it writes a script that writes `AUDITION.md`, and
  expects it. It prints the next steps: `git add .troupe` and `git commit -m "Add a troupe theatre"`, the allow line
  when policy doesn't allow the local stage, then `troupe perform lead --direction "<example>"`.
- `init` refuses where a theatre already exists, here or above (`theatre.exists`).
- `first-performance.md`'s tests (`packages/troupe/tests/test_user_docs_pages.py`) pull each `sh` block's lines off the
  page, assert they're exactly a known list, and run them through `troupe.cli.main`. The Claude Code section runs with
  `claude_stand_in`, a fake `claude` on `PATH`.
- `troupe perform` with uncommitted changes sends `workspace.uncommitted-unseen`, rendered on standard error as
  `troupe: <problem>` and `  fix: <fix>`. The rendering has no code in it, and the problem names a count and the first
  12 characters of HEAD.
- `install.md`'s command sits between release-please's markers, and `scripts/tests/workspace/test_install_docs.py`
  holds every copy of it to the one the install check runs.

## Goals / Non-Goals

**Goals:**

- A person following the pages from a fresh install gets a Claude Code run with their own character and direction, in
  their own repository, and the offline path still works.
- Every command on the first-run pages runs in the docs check, and the pages can't drift from what `init` prints.

**Non-Goals:**

- No new policy level or source: the permission is still an environment variable (#235, waiting for #71).
- `perform` doesn't commit for you (#232).
- No install script, and the install command doesn't change (#143).
- No change to what the audition defines: its options, character and direction stay as #260 made them.

## Decisions

### D1. The walkthrough is the audition's printed steps, with the character and direction made yours

The page follows `troupe init --audition` in order: run it, set your own character (D8), commit (the two commands
`init` printed), allow the local stage, then `troupe perform lead --direction "..."` with an example direction the
page invites the reader to replace. Reviewing (`diff`, `accept`, `discard`) and reading back (`status`, `logs`) follow,
as today.

Following the printed steps means one path, not two that agree by hand. A docs test runs `init --audition` and checks
the page's commit and allow lines are the lines it printed, so a change to either fails the check.

The character is written in a file of your own and set with `troupe config set actors.lead.character=@<file>`
(D8), not by editing `.troupe/actors/lead.md`.

The page's example direction differs from `init`'s on purpose: the point is that it's yours. The test runs the page's.

*Alternative:* define the Claude Code actor by hand with `troupe config set`, as the page's "instead" section does now.
Rejected as the lead: it's the step #232 set out to remove. It stays as the later "define your own actor" section (D4).

### D2. The page runs in "your own repository", so the notice comes up naturally

The page says to run it in a project you already have under git. There, you'll usually have changes you haven't
committed, so the page's step after the commit explains `workspace.uncommitted-unseen`: what it says, that the run
works from your latest commit and won't see them, and that you commit (or stash) first if the run needs them. troupe
doesn't commit for you.

The page shows the notice as a `text` block, as it's rendered, with an example count and commit. The docs test makes a
change after the commit, runs the page's `perform`, and compares standard error with the block, reading the example
count and commit as the run's own (a pattern made from the block, with those two as wildcards). The code
`workspace.uncommitted-unseen` is named in the prose, since the rendering doesn't print it.

*Alternative:* describe the notice without its text. Rejected: a described notice drifts silently when its wording
changes.

### D3. The offline path is a new repository with `--runner scripted`

`init` refuses where a theatre exists, so the offline path can't add a scripted actor to the theatre the reader just
made with the same command. It starts in a new directory: `git init`, `troupe init --audition --runner scripted`, then
the same printed steps, which need no account and no network. It's a short section after the main walkthrough, headed
as the way to try troupe offline with no account.

*Alternatives:* keep `hello.json` and `troupe config set` for the scripted actor in the same theatre. Rejected: it's
the hand-built actor #232 moved away from, and a JSON script of runner events is the hardest part of today's page. Or
`--audition` adding an actor to an existing theatre: rejected, it's a change to `init`'s refusals (cli spec), outside
this issue.

### D4. Defining your own actor stays, as a second Claude Code actor

After the walkthrough, a section defines a second actor with `troupe config set` (its runner and options from a
`claude.json`), with its character written in `.troupe/actors/<name>.md`. The notes on what the options mean (what the
agent may do, the budget, the login, what it doesn't load) move here from the "Run Claude Code instead" section, which
goes. The docs test runs it with the stand-in, as today.

This keeps what the page teaches now about config: nothing it covered is dropped, only reordered.

### D5. The permission: the same line, once, in your shell profile

The page's allow section gives the `export` line for sh, and the `$env:` line for PowerShell, and says to add it to
`~/.zshrc` or `~/.bashrc` (or the PowerShell profile, `$PROFILE`) once, and to run it in the current shell too. It then
applies to every theatre the reader runs. It says this is how it's given until policy files arrive, linking #71.

`init`'s note for the allow step says the same in one line, naming the profile for its platform: `~/.zshrc` or
`~/.bashrc` on Linux and macOS, `$PROFILE` on Windows. The platform is chosen where the line itself is (`_allow_line`,
by `sys.platform`), so the line and its note can't disagree.

*Alternative:* print a command that appends the line to the profile (`echo ... >> ~/.zshrc`). Rejected: troupe would be
telling people to edit a file whose shell it can only guess, and running it twice adds the line twice.

### D6. The install page: what you need, the command, the check, then the rest

`install.md` opens with uv as the one thing you need (linking its install page), the command for the latest release,
`troupe --version`, and the `uv tool update-shell` hint. A section below covers installing another release, `main` or
a commit, with what `--no-sources` does. The command and its release-please markers don't change, so the install
checks pass unchanged.

### D7. The pages stay `prerelease: true`

They describe `troupe init`, which ships in 0.2.0. The docs check's prerelease rules already apply.

### D8. You change the character with `config set`, until hand edits are read back

troupe writes `.troupe/actors/lead.md` from config and doesn't read edits to it back until #119 (0.3.0). An edited file
makes the next command that uses config refuse with `config.file-not-troupes`. `init --audition` said "edit it", which
led straight to that refusal (found while applying this change, owner's choice 2026-11-03).

So the page has you write your character in a file (`character.md`) and run
`troupe config set actors.lead.character=@character.md`: the file's text becomes the character, recorded with who set
it, and troupe writes `lead.md` from it. `init` prints that command in place of "edit it", with `<file>` for the file.
The line stays phrasing in the CLI, beside the files it lists: the core's result already says the actor has a
character.

`character.md` isn't committed by the page's `git add .troupe`, so it's one of the changes the uncommitted-changes
notice names (D2). The page says it can be deleted once it's set, since config holds the text.

When #119 lands, the page and `init` can go back to editing the file.

*Alternatives:* a separate Bug and change for `init`'s line first (rejected by the owner: two PRs for one first-run
text), or waiting for #119 (rejected: 0.3.0, and much larger).

## Risks / Trade-offs

- [The stand-in `claude` proves the commands run, not that a real Claude Code run succeeds] → The cli spec's "The
  printed steps work with Claude Code" scenario is checked by hand against a real Claude Code before the PR is marked
  ready, and the PR says so.
- [A reader in a repository with a theatre already can't run `init --audition`] → The page says `init` refuses there,
  and points to defining an actor (D4) instead.
- [The notice's pattern match could pass a changed notice if the change is only in the count or commit] → Those are the
  only wildcards, and both are values, not wording.
- [The page's walkthrough tests replace today's] → The new tests are written first and fail against the old page, and
  the refusal-until-allowed test keeps its shape.
