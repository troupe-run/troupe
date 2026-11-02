# Proposal: troupe init, and troupe init --audition

## Why

troupe never makes a theatre: a first run starts with `mkdir .troupe` by hand, and the first actor in the docs is the
scripted runner with a JSON script, nothing like real use. #232 (owner, 2026-11-01) decided that `troupe init`
makes a theatre and `troupe init --audition` also writes a working example actor, Claude Code by default, so a
first run is one command, a commit, and a `perform` with your own direction. This is #233, for 0.2.0. The
perform-status-logs design (2026-10-12) said `troupe init` would arrive with config, and it didn't.

## What Changes

- **`troupe init`** makes `.troupe/` in the current directory, with the `.gitignore` and `.gitattributes` troupe
  writes on its first record today. It records no event and sets up no actor.
  - It refuses where a theatre already exists, here or in any directory above, naming that theatre.
  - It refuses outside a git repository, naming `git init` as the fix. It never runs `git init` itself.
- **`troupe init --audition`** also writes a working example actor, `lead`, as one `Config.Changed` recorded
  through the same path as `troupe config set`. It then prints what to run next: commit `.troupe/`, allow the local
  stage when policy doesn't already, and `troupe perform lead --direction "..."` with an example direction.
  - **By default it's a Claude Code actor:** options with a small `maxBudgetUsd` (USD 1), `permissionMode:
    acceptEdits` and the file tools it needs, a short character in `.troupe/actors/lead.md` to edit, and no effect
    check, so any direction you type can succeed.
  - **`--runner <runner>` picks the runner** (only with `--audition`). `--runner scripted` writes an example that
    runs offline with no account: a script that writes one file, with an effect check on that file.
  - An unknown runner is refused with `runner.unknown`, naming the runners troupe has, before anything is made.
    It never falls through to Claude Code.
- **`--rehearse`** on both shows what would be made, recorded and written, and makes nothing.
- **Plain `init` and `init --audition` are one core command, `init`**, in the client protocol with its own request
  and result schemas. The CLI only parses and renders.
- **The VCS port says whether a directory is in a repository.** The git adapter answers from git and names
  `git init` when it isn't; the plain filesystem adapter always is.
- **`theatre.not-found`'s fix names `troupe init`**, not `mkdir .troupe`.
- **Two new error codes:** `theatre.exists` and `vcs.not-a-repository`, each with a details schema in the protocol.
- **Docs follow:** `docs/prompt-book/cli.md` (the command, and the generated reference), a glossary row for
  "audition", and the sentences in `first-theatre.md` and `theatres.md` that say troupe never makes a theatre.
  Rewriting the first-run walkthrough to lead with a real agent is #234, not this change.

Nothing is **BREAKING**: `init` is a new command and a new protocol method. Changing a fix's wording breaks nothing
that reads the error as data.

## Capabilities

### New Capabilities

None. Making a theatre belongs with finding one, which `cli` already specifies.

### Modified Capabilities

- `cli`: a new `troupe init` command, with `--audition`, `--runner` and `--rehearse`, its refusals and what it
  prints. The theatre-finding requirement's fix names `troupe init`.
- `config`: what `init --audition` records. That's one `Config.Changed` for the example actor, checked like any
  other change, and its runner and options for Claude Code and for the scripted runner.
- `client-protocol`: `init` is a protocol command, with a request that names no path, and a result that validates.
- `vcs`: the VCS port says whether a directory is in a repository. The git adapter refuses outside a work tree,
  naming `git init`.

## Impact

- **Code:** a new `troupe.core.init` command module (making the theatre, building the example actor, the next
  steps), sharing `config_set`'s recording path rather than copying it. A new `troupe init` in `troupe.cli`, plus
  `troupe.core.theatre` (`theatre.not-found`'s fix) and `troupe.core.errors` (two codes). The `Vcs` protocol gets a
  repository check, implemented by `troupe-vcs-git` and `troupe-vcs-files`.
- **Protocol:** `protocol/schemas/client/init-request.schema.json` and `init-result.schema.json`, and details
  schemas for the two new codes in `error.schema.json`. This is a minor protocol release (new messages, no breaking
  change).
- **Docs:** `docs/prompt-book/cli.md` (hand-written part and regenerated reference) and
  `docs/prompt-book/glossary.md`, plus small corrections in `docs/opening-night/first-theatre.md` and
  `docs/the-company/theatres.md`.
- **No new spec**, and no spec Purpose changes, so troupe-run/infrastructure's `oob/troupe-spec-purposes.json`
  needs no update.
- **Related:** #234 (first-run pages), #235 (local-stage permission given once), troupe-run/website#85 ("audition"
  in the brand guide).
