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

Write a script that writes a file, in your theatre:

```json title="hello.json"
{"script": {"steps": [
  {"event": {"type": "init", "runner": {"name": "scripted", "version": "0.1.0"}, "tools": ["Write"]}},
  {"writeFile": {"path": "out/hello.txt", "content": "hello\n"}},
  {"event": {"type": "result", "status": "ok", "message": "wrote out/hello.txt"}}
]}}
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
troupe perform tester --runner scripted --runner-options hello.json --expect out/hello.txt
```

`tester` is the actor's name. `--expect out/hello.txt` is what the run is for: troupe checks afterwards that the
file was created or changed, and the run fails if it wasn't. Until config arrives, you name the runner and its
options on the command line each time ([#60](https://github.com/troupe-run/troupe/issues/60)).

While it runs, troupe shows its progress on standard error. When it succeeds, standard output gets one line,
`run <id> succeeded`, and `out/hello.txt` says `hello`.

## Read it back

```sh
troupe status
troupe logs <run>
```

`troupe status` lists your runs, newest first. `troupe logs <run>` shows one run's events in order, each with when
troupe recorded it: name the run by its id or its first 8 characters. Add `--follow` to watch a run from another
terminal while it's going.

Everything you've seen is recorded in `.troupe/events/`, with who started the run, on which stage, and why it was
allowed to run there. [Performances and runs](../the-company/performances-and-runs.md) says what a run records, and
[Read the lineage](../stagecraft/read-the-lineage.md) how to answer questions from it.
