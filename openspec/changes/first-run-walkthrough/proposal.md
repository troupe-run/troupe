# Proposal: the first run leads with a real agent and your own prompt

Issue: troupe-run/troupe#234. Decided in #232 (owner, 2026-11-01), with the local-stage permission's first-run text
from #235 (owner, 2026-11-03).

## Why

The first-run pages still walk a new person through the scripted runner first: a JSON script of runner events, an
actor defined by hand with `troupe config set`, and Claude Code last, as "instead". That's nothing like real use. #233
(PR #260) shipped `troupe init` and `troupe init --audition`, which make the theatre and a working Claude Code actor in
one command, but `first-performance.md` doesn't use them, and `first-theatre.md` only mentions them. The local-stage
permission is still taught as an `export` for every shell, and `init --audition`'s own note says the same.

## What Changes

- **`first-performance.md` leads with Claude Code, in your own repository.** It starts from `troupe init --audition`:
  you edit the character it wrote (`.troupe/actors/lead.md`), commit, allow the local stage, and run
  `troupe perform lead --direction "..."` with a direction you type. Reviewing (`diff`, `accept`, `discard`) and
  reading back (`status`, `logs`) follow, as today.
- **The page shows `workspace.uncommitted-unseen`**, and why a run starts from your latest commit: in your own
  repository you'll usually have changes the run won't see, and troupe tells you rather than committing for you.
- **The scripted runner is the "try it offline, with no account" path:** `troupe init --audition --runner scripted`,
  in a new repository, then the same steps.
- **Defining an actor of your own stays on the page,** shorter: a second Claude Code actor through `troupe config set`,
  with a character you write in `.troupe/actors/<name>.md`. What the Claude Code options mean (permissions, budget,
  login) stays.
- **The local-stage permission is given once, in your shell profile.** The page says to add
  `export TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE=true` to `~/.zshrc` or `~/.bashrc` (or
  `$env:TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE = "true"` to the PowerShell profile), and that it then applies to
  every theatre you run. Policy is still read from the environment only (#235).
- **`troupe init --audition`'s note for the allow step says the same,** in place of "Set this in each shell you
  perform from", naming the profile files for the platform it runs on.
- **`first-theatre.md` leads with `troupe init`,** says what `--audition` adds (the `lead` actor's two files), and
  drops its "Config, when it comes" section, since config has come.
- **`install.md` presents the install command better** (docs only, #232 question 5): what you need first (uv, with
  where to get it), the one command for the latest release, and how to check it worked, at the top. Installing another
  release, `main` or a commit, and what `--no-sources` is for, move below it. The command itself doesn't change, and
  the install checks still hold every copy of it to the one the install check runs.
- **The docs tests follow the pages.** They run the Claude Code walkthrough as written with the stand-in `claude`, run
  the offline walkthrough as written with the scripted runner, show the page's next steps are the ones
  `init --audition` prints, and show the uncommitted-changes notice the page describes is the one `perform` sends.

Assumption, recorded rather than asked: "presented better" for the install line means the layout above. Nothing
shortens the command itself before #143 decides how troupe reaches people who don't use uv.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `user-docs`: adds that the first-run walkthrough leads with Claude Code from `troupe init --audition`, keeps an
  offline path with the scripted runner, and runs as written in the docs check, and that it says to give the
  local-stage permission once, in the shell profile.
- `cli`: `troupe init --audition`'s allow step says to add the line to your shell profile once, so it applies to every
  theatre you run (the requirement "Init prints the next steps for its audition").

## Impact

- `docs/opening-night/first-performance.md`, `first-theatre.md`, `install.md`.
- `packages/troupe/src/troupe/cli/init.py` (the allow step's note), and its tests in
  `packages/troupe/tests/test_cli_init.py`.
- `packages/troupe/tests/test_user_docs_pages.py`: the first-performance tests are rewritten for the new walkthrough.
- No change to policy, config, the protocol, or any event. No new spec, so troupe-run/infrastructure's
  `oob/troupe-spec-purposes.json` is unchanged.
