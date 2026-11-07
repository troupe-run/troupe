---
title: Your first performance
description: Running your process once.
status: written
prerelease: true
---

A performance is one run of your process. Today troupe runs one actor at a time, so your first performance is one
actor's run: troupe starts it, records everything it reports, checks it did what it was for, and lets you read it
back. Running your whole process end to end, through every role, comes later: it needs
[flows](../the-company/flows.md), [roles](../stagecraft/configure-roles.md) and
[gates](../the-company/gates-and-decisions.md), none of which are built yet.

This page runs [Claude Code](https://code.claude.com) on your own code, in a git repository you already have, with a
character you write and a direction you type. You need Claude Code installed and logged in. Without an account, [try
it offline](#try-it-offline-with-no-account) instead.

## Audition an actor

In the directory you want troupe to work in, at the top of your code or anywhere in it:

```sh
troupe init --audition
```

This makes the [theatre](first-theatre.md) and defines a working example actor, `lead`. An actor is config: its
runner, the runner's options, and what a run of it is for. `lead`'s runner is `claude-code`, and its options let
Claude Code read your files and write them, with a budget of USD 1 a run. troupe writes it to
`.troupe/actors/lead.yaml`, so you can read it, and review it as a diff. `troupe init` then prints what to run next,
which is what the rest of this page does.

`troupe init` refuses where there's a theatre already. If you have one, [define your own
actor](#define-your-own-actor) in it instead.

## Write its character

An actor's **character** is the prompt it runs with: the Claude Code runner adds it to Claude Code's system prompt.
`lead` has one to start with, in `.troupe/actors/lead.md`. Write your own in a file, such as:

```markdown title="character.md"
You are a technical writer joining this team. Read what's there before you write anything, keep what you write
short and plain, and finish by saying which files you read.
```

Then make it `lead`'s character:

```sh
troupe config set actors.lead.character=@character.md
```

`@character.md` reads the text from the file. troupe records the change with who made it, and writes
`.troupe/actors/lead.md` from it. Change the character this way, not by editing `lead.md`: troupe can't read edits
to its files back yet ([#119](https://github.com/troupe-run/troupe/issues/119)), so the next command would stop with
`config.file-not-troupes` rather than overwrite yours. Config holds the text now, so you can delete `character.md`.

## Commit

A run works in its own copy of your theatre, made from your latest commit, so commit the theatre:

```sh
git add .troupe
git commit -m 'Add a troupe theatre'
```

## Allow the local stage, once

An actor runs on a [stage](../the-company/performances-and-runs.md#stages). The only stage so far runs it as a
process on your machine, where troupe can't stop it touching files or hosts it shouldn't. So troupe refuses to run
anything there until you say it may, with a policy setting. For now that's an environment variable. Run its line:

```sh
export TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE=true
```

Then add the same line to your shell profile, `~/.zshrc` or `~/.bashrc`, once. Every new shell then has it, and it
applies to every theatre you run. On Windows, the line for PowerShell is:

```powershell
$env:TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE = "true"
```

and its profile is the file `$PROFILE` names. Each run on the local stage still records that its effects weren't
enforced. When [policy files](https://github.com/troupe-run/troupe/issues/71) arrive, the setting moves to one.

## Perform

Say what this run is for with `--direction`. This one is an example: type your own.

```sh
troupe perform lead --direction "Write NOTES.md: what this code is for, in a few lines"
```

`lead` is the actor's name, and troupe takes the rest from config. Add `--rehearse` to see what would run without
starting anything.

While it runs, troupe shows its progress on standard error. When it succeeds, standard output gets one line,
`run <id> succeeded`.

The run worked in its own git worktree, under `.troupe/local/worktrees/`, so your files haven't changed yet:
`NOTES.md` is in the worktree, not beside your files. That's a worktree's whole point: you see what an actor did
before any of it is yours.

## Changes the run won't see

A run starts from your latest commit, so it doesn't see what you haven't committed: here, `character.md`, and any
other changes you have. troupe tells you, with the notice `workspace.uncommitted-unseen`, and runs anyway:

```text
troupe: 1 path(s) differ from HEAD (3f9c2a1b7d4e), and the run won't see them: it works in its own worktree, made from HEAD. Accepting its changes may conflict with yours.
  fix: Commit or stash your changes first if the run needs them. Otherwise, nothing to do.
```

troupe doesn't commit for you. If the run needs your changes, commit them, or stash them, and perform again.

## Keep it, or not

```sh
troupe diff <run>
troupe accept <run>
```

`troupe diff <run>` shows what the run changed, as a diff. `troupe accept <run>` applies it to your files, unstaged,
so `NOTES.md` is now beside your files and `git diff` shows it like any change of your own. `troupe discard <run>`
throws it away instead. A worktree catches an actor's mistakes, not its intent: it can still write outside the
worktree, and [discarding doesn't undo](../the-company/performances-and-runs.md#workspaces) what it does to git
itself.

## Read it back

```sh
troupe status
troupe logs <run>
```

`troupe status` lists your runs, newest first. `troupe logs <run>` shows one run's events in order, each with when
troupe recorded it: name the run by its id or its first 8 characters. Add `--follow` to watch a run from another
terminal while it's going.

Everything you've seen is recorded in `.troupe/events/`, with who started the run, on which stage, why it was
allowed to run there, and which version of config it used. [Performances and
runs](../the-company/performances-and-runs.md) says what a run records, and [Read the
lineage](../stagecraft/read-the-lineage.md) how to answer questions from it.

## Try it offline, with no account

troupe ships a second runner, the scripted runner, which plays a script instead of running an agent. It needs no
account, costs nothing and works offline, and it's how troupe's own tests run. Try it in a new git repository:

```sh
mkdir troupe-offline
cd troupe-offline
git init
troupe init --audition --runner scripted
git add .troupe
git commit -m 'Add a troupe theatre'
troupe perform lead
```

Allow the local stage first, as above, if this shell doesn't have it. The run writes `AUDITION.md` in its worktree,
and troupe checks it did: the actor's `expect` names the file, and a run that didn't create or change it fails.
`troupe diff`, `accept`, `status` and `logs` work as they do above.

## Try it with a model on your own machine

troupe ships a third runner, the Ollama runner, which runs a model on your own computer through
[Ollama](https://ollama.com). It needs no account and no credential, costs nothing per run, and works offline once
the model is downloaded. You need Ollama 0.12.6 or later, running. Try it in a new git repository:

```sh
ollama pull qwen3.5:4b
mkdir troupe-local
cd troupe-local
git init
troupe init --audition --runner ollama
git add .troupe
git commit -m 'Add a troupe theatre'
troupe perform lead
```

Allow the local stage first, as above, if this shell doesn't have it. The model is about 3.4 GB to download. The
actor names it (`model`), and the [runtime](../stagecraft/runtimes.md) its runs talk to: `ollama`, troupe's built-in
one for the Ollama on your machine (`http://127.0.0.1:11434`). Point it at an Ollama elsewhere with
`troupe config set runtimes.ollama.endpoint=<url>` for the theatre, or `TROUPE_RUNTIME_OLLAMA_ENDPOINT` for you alone.
The actor's options can give the model a larger context window (`contextLength`, 16384 tokens unless you set it). A
small local model is less reliable at using tools
than Claude Code: troupe's effects and audit still decide what a run may change, and a run that outgrows its context
window fails rather than carrying on with its direction cut off. The
[Ollama runner's README](https://github.com/troupe-run/troupe/blob/main/plugins/runner-ollama/README.md) lists every
option.

## Try it on OpenAI

troupe ships a fourth runner, the OpenAI runner, which runs an OpenAI model through its Responses API, with troupe's own
tool loop. It needs an OpenAI API key in `OPENAI_API_KEY`, and **a run costs money**, on your OpenAI account. troupe
never writes the key down: config only names the variable it's in. Set the key first.
Try it in a new git repository:

```sh
mkdir troupe-openai
cd troupe-openai
git init
troupe init --audition --runner openai
git add .troupe
git commit -m 'Add a troupe theatre'
troupe perform lead
```

Allow the local stage first, as above, if this shell doesn't have it. The actor runs on the built-in `openai` runtime
with a small, cheap model, and a small budget: a run stops after 10 requests, or once it has used 100,000 tokens. Each
response is counted whole, so a run can end a little over. A run that stops says which option to raise (`maxTurns`,
`maxTotalTokens`). When you define your own actor on it, start with
lower limits still, such as `maxTurns` 5 and `maxTotalTokens` 20,000, and raise them once it behaves.
[Point actors at a service](../stagecraft/runtimes.md) says how to use another model, another key, or another service
that serves the Responses API. The
[OpenAI runner's README](https://github.com/troupe-run/troupe/blob/main/plugins/runner-openai/README.md) lists every
option.

## Define your own actor

`troupe init --audition` is one way to define an actor. `troupe config set` is the other, and works in any theatre.
Write the actor's options, which set its budget and the tools it may use besides editing, and its character:

```json title="claude.json"
{"allowedTools": ["Read", "Glob", "Grep"], "maxBudgetUsd": 1}
```

```markdown title="reviewer.md"
You are a reviewer. Read the change you're asked about, say what's wrong with it and why, and change nothing but the
file you're asked to write.
```

Then set all of it in one change, commit, and perform:

```sh
troupe config set actors.reviewer.runner=claude-code actors.reviewer.options=@claude.json actors.reviewer.character=@reviewer.md 'actors.reviewer.expect=[]' 'actors.reviewer.effects.write=["REVIEW.md"]'
git add .troupe
git commit -m 'Add the reviewer actor'
troupe perform reviewer --direction "Review the last commit, and write what you found in REVIEW.md"
```

`expect` is what a run is for: the paths it must create or change, or `[]` when no file has to, so any direction can
succeed. `effects` is what a run may change: here, only `REVIEW.md`.

- **What the agent may change is up to its effects.** troupe turns `effects.write` into Claude Code's own permission
  rules, so the reviewer can write `REVIEW.md` and nothing else. With nothing declared, it may read but not write.
  The run reports each tool it was denied, rather than doing nothing silently, and troupe checks afterwards that
  nothing changed outside what's declared ([Effects](../the-company/performances-and-runs.md#effects)).
- **Every run has a budget:** `maxBudgetUsd`, or USD 5 when it isn't set. Claude Code stops when it's spent.
- **Claude Code uses your existing login,** or `CLAUDE_CODE_OAUTH_TOKEN` or `ANTHROPIC_API_KEY` when one is set. It
  doesn't load your Claude Code settings, hooks or MCP servers, or the theatre's, or its `CLAUDE.md`: a run doesn't
  depend on whose machine it's on. The option `settingSources` loads them again.

The [Claude Code runner's README](https://github.com/troupe-run/troupe/blob/main/plugins/runner-claude-code/README.md)
lists every option.
