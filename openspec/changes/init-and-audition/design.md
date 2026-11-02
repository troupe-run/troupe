# Design: troupe init, and troupe init --audition

## Context

See proposal.md for why. What exists today and shapes the approach:

- **Finding a theatre** is `troupe.core.theatre.find_theatre`: the nearest `.troupe/` directory upwards, else
  `theatre.not-found`, whose fix today says `mkdir .troupe`. The theatre's git files are written by
  `ensure_git_files`, which config's projection calls on every write into `.troupe/`.
- **Every surface calls the core through the client protocol's dispatcher** (`troupe.core.client.dispatch.call`)
  with a `Session` that holds the theatre's path. The CLI builds that session from `find_theatre(Path.cwd())`,
  which can't work for `init`, because there's no theatre yet.
- **Config changes** go through `config_set` (`troupe.core.config.commands`). It takes the files' lock, plans and
  stages the files, records one `Config.Changed`, then moves the files into place. A crash between recording and
  moving is finished by the next flush (config-model design D9).
- **Runners troupe knows** are `troupe.core.interim.RUNNERS` (`claude-code`, `scripted`). `interim.runner(name)`
  refuses an unknown name with `runner.unknown`, naming the known ones, and `interim.options_validator` checks
  options against a runner's published schema.
- **The CLI parser** runs its own checks before argparse and supports options that take exactly one value or none.
  It refuses `nargs="?"` (`_declared` raises `internal.unexpected`).
- **VCS** is the `Vcs` protocol (`troupe.core.vcs`), with `defaults.VCS = "git"`. The git adapter runs git in the
  theatre's directory, and nothing yet asks whether that directory is in a repository at all.
- **Policy** is read through `troupe.core.policy`, from the session's environment only. The local stage refuses every
  actor unless `TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE=true`. Giving that once is #235.

## Goals / Non-Goals

**Goals:**

- One core command, `init`, that plain init and the audition share, so a run server can offer it unchanged.
- The audition's actor is recorded exactly as a `troupe config set` would record it: same checks, same lineage, same
  files, through the same code.
- Every refusal comes before anything is made, and a failure part-way leaves nothing behind that blocks trying again.
- What the example actor holds is decided in one named place.

**Non-Goals:**

- Running `git init`, or any git command that changes the repository (#232 rejected it).
- Adding an audition to an existing theatre. `init` refuses there, and `troupe config set` already defines actors.
- Detecting a theatre **below** the working directory. The issue covers here and above only.
- A flag to name the example actor, or to set its options. Edit the config afterwards.
- Giving the local-stage permission once (#235), and rewriting the first-run pages (#234).
- Checking that Claude Code is installed or logged in. `perform` already reports that clearly when it runs.

## Decisions

### D1. One core command, `init`, run in a session whose theatre is the working directory

`init` is a client-protocol command like `config-set`, with `init-request` and `init-result` schemas. The CLI builds
its session with `theatre=Path.cwd()`, the directory where the theatre would be made, without calling
`find_theatre`. The core does every check itself, including looking for a theatre above (D2). So a run server can
offer the same command, with a session pointing at the directory it would make the theatre in. No request names a
path (spec: client-protocol).

*Alternative:* do it in the CLI, as `mkdir` and then `config set`. Rejected because the CLI must not hold behaviour
(project context: thin client), and two commands would mint two change ids, with a gap between them where a
half-made theatre exists.

### D2. Check everything first, then make, then record

The order:

1. `.troupe` exists here or above → `theatre.exists`, naming the theatre's root (or the file, when `.troupe` here
   isn't a directory).
2. The VCS adapter says the directory isn't in a repository → `vcs.not-a-repository` (D7).
3. With an audition: the runner is known (`interim.runner`, so `runner.unknown` is the same error everywhere), the
   example actor's entries are built against empty config, and checked against the actor schema and the runner's
   options schema.
4. With an audition: the identity is resolved through the same identity chain the store uses. No identity fails
   here.
5. **Make:** create `.troupe/` and write its git files with `ensure_git_files`, the function every write already
   uses, so a theatre made by `init` is byte-for-byte what a first record makes today.
6. **Record:** with an audition, record the change through config's shared recording path (D3), passing the identity
   resolved in step 4.

When step 5 or 6 fails before the event is recorded, `init` removes the `.troupe/` it made. It made it in this
command, so it holds nothing of anyone else's. Once the event is recorded, `init` leaves the theatre, and the next
command's flush finishes any file not yet moved into place, as config-set's recovery already does. A rehearsal runs
steps 1 to 4 and reports what steps 5 and 6 would do, opening no store.

*Alternative:* make the directory first and let `config_set` fail later. Rejected because a failed audition would
leave a theatre that `init` then refuses, so trying again would need a hand `rm -rf`.

### D3. The audition records through config-set's path, not a copy of it

The body of `config_set` that records (lock, plan, stage, record, move) moves into one function that both
`config-set` and `init` call with a list of operations. The audition's operations set each of the actor's values
(`actors.lead.runner`, `.options.*`, `.expect`, `.character`), so the change's entries are exactly what
`troupe config set` with the same values would record. That means one `Config.Changed` (spec: config, "A command
records one change"), with `via: cli` and a command cause.

### D4. `--audition` takes no value; `--runner <runner>` names the runner

```text
troupe init [--audition [--runner <runner>]] [--rehearse]
```

`--runner` without `--audition` is refused as `usage.missing-argument`, naming `troupe init` and `--audition`. The
CLI command raises this after parsing, since the parser has no "requires" shape. The runner's name isn't
constrained to argparse choices. The core checks it, so `runner.unknown` names the runners exactly as `perform` and
`config set` do.

*Alternatives:*

- `--audition[=<runner>]` (an option with an optional value). It reads well, but the parser refuses `nargs="?"`,
  and adding it changes the pre-argparse scan that #53's regression showed is easy to break. That's more risk than
  a second flag is worth.
- `--audition <runner>` with the value required. Rejected because Claude Code must be the default (#232).

The issue left this choice to the design, so **this is for the owner to confirm at review.**

### D5. The two refusals exit 1, not the usage code

`theatre.exists` and `vcs.not-a-repository` exit with 1 (`FAILURE`), like `theatre.not-found`. The exit-code table
defines 2 as "the command line was not understood", and here it was understood. The issue's wording says these
refuse "with a usage error naming the fix", which reads as describing the message rather than the exit code.
**This is for the owner to confirm at review.** If 2 is wanted, the change is one line each in
`troupe.core.errors`, plus the scenarios' codes.

### D6. The example actor is defined in one module, `troupe.core.audition`

It holds the actor's name, `lead`, and an audition per runner, keyed by the runner's name. Each audition is the
actor's values and an example direction. A test checks that every runner in `interim.RUNNERS` has one, so adding a
runner without an audition fails the check rather than falling through.

- **The name `lead`** is short, theatrical, and reads naturally in `troupe perform lead`. One name for every runner,
  so the docs and printed steps don't depend on the runner.
- **Claude Code** gets `maxBudgetUsd: 1` (small, and the figure the first-run page already uses), `permissionMode:
  acceptEdits`, `allowedTools: [Read, Write, Edit, Glob, Grep]` (enough to read the repository and write a file, and
  no `Bash`), and `expect: []`. With no effect check, the direction you type can succeed whatever it touches. The
  run's worktree, and `troupe diff` and `accept`, are what you review. Its character is two or three plain sentences
  about working carefully in the repository and saying what changed. The "edit this file" hint goes in the printed
  output, not in the prompt, because the character is sent to the model verbatim.
- **Scripted** gets an inline script with an `init` event, a `writeFile` of `AUDITION.md`, and an `ok` result, plus
  `expect: ["AUDITION.md"]`. The effect check is shown where it can't fail by chance. The `init` event reports the
  installed scripted runner's version, read from its package metadata, so the event is true. It gets no character,
  because the scripted runner doesn't read one, and a prompt file that does nothing would mislead.
- **The example direction** names the same file for both: "Write AUDITION.md: a short note on what this repository
  holds, for someone new to it." It works in an empty repository, and the name is unlikely to collide with a file
  someone already has.

### D7. The VCS port gets `check_repository()`

`Vcs.check_repository() -> None` raises `vcs.not-a-repository` when the adapter's directory isn't in one of its
repositories. Each adapter supplies the fix, because only the adapter knows how to make a repository.

- The git adapter runs `git rev-parse --is-inside-work-tree` in the directory. Exit 128, or any output other than
  `true` (as in a `.git` directory or a bare repository), means it isn't. It's a read-only, local command within
  the adapter's existing limits and environment policy.
- The plain filesystem adapter always passes.

The error is a core code with a details schema (`directory`, `adapter`), and its fix text comes from the adapter.

### D8. Next steps are data in the result; the CLI phrases them

An audition's `init-result` carries `steps`, in order:

1. `{"kind": "commit", "paths": [".troupe"]}`, when the adapter has commits (git).
2. `{"kind": "allow-local-stage", "variable": "TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE", "value": "true"}`, only
   when the session's policy doesn't already allow it. Policy is read through its seam, so a malformed value fails
   `init` as it would fail `perform`.
3. `{"kind": "perform", "actor": "lead", "runner": "<runner>", "direction": "<example>"}`.

The CLI renders them as commands to copy:

- `git add .troupe` and `git commit -m "Add a troupe theatre"`. It stages only `.troupe`, never `-A`, so it doesn't
  sweep up someone's unrelated work.
- `export ...=true` on Linux and macOS, `$env:... = "true"` on Windows.
- `troupe perform lead --direction "..."`, with a note for `claude-code` that Claude Code must be installed and
  logged in, and a pointer to `.troupe/actors/lead.md` to edit the character.

Plain `init` has no steps. The CLI prints the theatre and its files, and says `troupe init --audition` adds an
example actor.

### D9. Output streams and exit codes

On success, `init`'s report goes to standard output, notices go to standard error, and it exits 0. A rehearsal shows
the same report as "would" and exits 3 (`WOULD_CHANGE`). `init` never has nothing to do, because a theatre that
exists is refused. Refusals print to standard error and exit with their codes (D5).

## Risks / Trade-offs

- **The Claude Code path can't run in CI** (no login, and it costs money). → The scripted path is tested end to end
  in CI on all three platforms: init, then the printed commit and policy step, then the printed perform. The Claude
  Code path is checked once by hand before the PR is marked ready, and the result goes in the PR. The unit tests
  check its config against the runner's published options schema.
- **A theatre below the working directory** (running `init` at a repository root when `app/.troupe/` exists) makes a
  second theatre. Commands in `app/` then find the inner one. → This is out of scope, as the issue covers here and
  above. It's noted in the docs' theatres page, and worth a follow-up issue if it bites.
- **Removing `.troupe/` after a failed record** could, in principle, remove something written into it by another
  process during the command. → `init` refused if `.troupe` existed at step 1, so only a concurrent `init` could race
  it. The removal deletes only paths `init` itself wrote, and leaves a directory that has anything else in it.
- **The example's wording and budget are product choices.** → They live in one module (D6) and can change in a later
  release without any spec change beyond the scenario values.
- **The printed policy step** has to be repeated in every shell until #235. → It's printed only when needed, and it
  names the variable, so #235 can replace the step without changing the steps' shape.

## Migration Plan

Nothing to migrate: `init` is new, and theatres made by hand stay valid. It's a minor protocol release (new
messages) and a minor troupe release.
