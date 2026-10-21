---
title: Performances and runs
description: One run of your process.
status: written
prerelease: true
---

A **performance** is one run of your process, through the roles it needs. A **run** is one actor's part in it:
troupe starts the actor through its runner, records everything it reports, and works out how it ended.

Today troupe runs one actor at a time, with `troupe perform`, so a performance is a single run. A performance that
takes your process through several roles needs [flows](flows.md), and isn't built yet. A **rehearsal** will be the
dry-run counterpart of a performance, and isn't built yet either.

## A run

`troupe perform <actor>` runs one actor, as config defines it: its runner, the runner's options, its effect check
and its character. `--direction` says what this run is asked to do.

1. **Everything that can refuse goes first:** who you are, the policy, whether the stage admits the actor, the
   actor's config (an actor config doesn't have, or config with a [conflict](../stagecraft/hand-edit-config.md#branches),
   is refused), and the runner's name. A refused `perform` runs nothing and records nothing.
2. **The config files are made what config says,** as every command that uses config does first.
3. **The run gets an id,** shown at once, so you can follow it from another terminal.
4. **The direction is stored** and referred to by hash, since it can be large or hold what shouldn't be in git.
5. **Each event the runner reports is recorded as it arrives,** then the run's end, with its outcome.

`troupe perform <actor> --rehearse` makes every check in step 1 and stops there: it shows what would run, and
starts and records nothing.

[Your first performance](../opening-night/first-performance.md) walks through one, and the [CLI](../prompt-book/cli.md)
lists every option.

## What a run records

A run is recorded as its own stream of [events](../prompt-book/events.md), all sharing one change id:

- **`Run.Started`:** the actor, the runner you asked for and the one that answered, the stage and what allowed it,
  the effect check, a reference to the direction, and the config version the run used, so what the actor was then
  can always be worked out. You started it, through the command line.
- **`Run.Reported`:** one for each event the runner reports, in order. The agent reported it, through its runner.
- **`Run.Ended`:** the outcome, its error, the runner's result, references to the transcript and standard error, and
  the limits the run ran under.

If an event can't be recorded, troupe stops the run, so the record never has a gap, and still records the end if it
can, saying where recording stopped and why. The transcript is always kept.

## How a run ends

troupe works out the outcome from everything it saw, never from the runner's exit code alone. A run **succeeds**
only when the runner reports an `ok` result, the effect check passes and the runner exits cleanly. Otherwise it has
failed, was cancelled, timed out, crashed or couldn't start, and the error says which and why.

**The effect check** is what the run was for: `--expect` names each file the run must create or change, and troupe
checks them afterwards. `--no-effect-check` says there's nothing to check. One of the two is required.

**Ctrl-C** cancels the run: troupe asks the runner to stop, gives it a grace period, then stops it and everything it
started. The run is recorded as `cancelled`, and `perform` exits 130.

## A run's state

A run's state isn't recorded: it's worked out from the events each time you read them.

| State | When |
|---|---|
| `ended` | The run's end is recorded |
| `running` | No end yet, and the `troupe perform` running it is still going in this clone |
| `interrupted` | No end, and the `troupe perform` that ran it in this clone stopped without recording one |
| `unfinished-elsewhere` | No end, and it was started in another clone, which this one can't see |

troupe never records anything on behalf of an interrupted run: how it ended would be a guess. Its events and
transcript show how far it got.

## Stages

A **stage** is where an actor runs. Before a run starts, the stage admits the actor or refuses it, and a refused
actor isn't run.

The only stage so far is the **local stage**, which runs the actor as a process on your machine, in the theatre. A
process there can write any file and reach any host you can, so troupe can't enforce what the actor may touch. The
local stage therefore refuses every actor unless policy allows it, and every event the run records says its effects
weren't enforced and which setting allowed it.

`--expect` isn't enforcement: it checks afterwards that the actor did what it was for. Two things are planned:
- a stage that can enforce what an actor may touch, in a container
  ([#65](https://github.com/troupe-run/troupe/issues/65));
- a git worktree for each run on the local stage, so you can see exactly what a run changed and keep or discard it
  ([#51](https://github.com/troupe-run/troupe/issues/51)).

## Policy

Policy decides what troupe may do, whoever asks. No command can loosen it.

| Setting | Default | What it allows |
|---|---|---|
| `allow_unenforced_local_stage` | `false` | Running an actor on a stage that can't enforce its declared effects, such as the local stage |

Until policy has files of its own ([#8](https://github.com/troupe-run/troupe/issues/8)), you set it with an
environment variable, `TROUPE_POLICY_` and the setting's name in capitals:

```sh
export TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE=true
```

The value must be exactly `true` or `false`. Anything else, such as `yes` or `1`, fails the command with
`policy.invalid-value`, and never falls back to the default. Unset or empty means the default.

## When the house runs runs

Today a run lasts as long as the `troupe perform` that started it. Once the [house](the-house.md) is built, it
supervises runs, so they carry on beyond the terminal that started them.
