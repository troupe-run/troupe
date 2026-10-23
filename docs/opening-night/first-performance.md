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

You need a [theatre](first-theatre.md) to work in.

## Choose a runner

A runner is what runs an actor: it starts the agent and passes on what it does. Today there's one, the scripted
runner, which plays a script instead of running an agent. It's how you try troupe out offline, and how troupe's own
tests run. A runner for Claude Code comes next ([#55](https://github.com/troupe-run/troupe/issues/55)).

Write a script that writes a file, in your theatre. It's the scripted runner's options:

```json title="hello.json"
{"script": {"steps": [
  {"event": {"type": "init", "runner": {"name": "scripted", "version": "0.1.0"}, "tools": ["Write"]}},
  {"writeFile": {"path": "out/hello.txt", "content": "hello\n"}},
  {"event": {"type": "result", "status": "ok", "message": "wrote out/hello.txt"}}
]}}
```

## Define the actor

An actor is config: its runner, the runner's options, and what a run of it is for. Set all three in one change:

```sh
troupe config set actors.tester.runner=scripted actors.tester.options=@hello.json 'actors.tester.expect=["out/hello.txt"]'
```

`actors.tester.options=@hello.json` reads the options from the file. `expect` is what the run is for: troupe checks
afterwards that `out/hello.txt` was created or changed, and the run fails if it wasn't. troupe records the change
with who made it, and writes `.troupe/actors/tester.yaml`, so you can read the actor, and review it as a diff.

## Commit

A run works in its own copy of your theatre, made from your latest commit, so commit what the actor should see:

```sh
git add -A
git commit -m "Add the tester actor"
```

## Allow the local stage

An actor runs on a [stage](../the-company/performances-and-runs.md#stages). The only stage so far runs it as a
process on your machine, where troupe can't stop it touching files or hosts it shouldn't. So troupe refuses to run
anything there until you say it may, with a policy setting. For now that's an environment variable:

```sh
export TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE=true
```

On Windows, in PowerShell, that's `$env:TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE = "true"`.

## Perform

```sh
troupe perform tester
```

`tester` is the actor's name, and troupe takes the rest from config. Add `--direction "..."` to say what this run is
for, and `--rehearse` to see what would run without starting anything.

While it runs, troupe shows its progress on standard error. When it succeeds, standard output gets one line,
`run <id> succeeded`.

The run worked in its own git worktree, under `.troupe/local/worktrees/`, so your files haven't changed yet:
`out/hello.txt` is in the worktree, not beside your files. That's a worktree's whole point: you see what an actor
did before any of it is yours.

## Keep it, or not

```sh
troupe diff <run>
troupe accept <run>
```

`troupe diff <run>` shows what the run changed, as a diff. `troupe accept <run>` applies it to your files, unstaged,
so `out/hello.txt` now says `hello` and `git diff` shows it like any change of your own. `troupe discard <run>`
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
