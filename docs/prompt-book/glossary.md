---
title: Glossary
description: The words troupe uses, and what each one means.
status: written
prerelease: false
---

| Term | Meaning |
|---|---|
| theatre | A project directory with troupe config |
| role | A job in your process, such as product owner, engineer or reviewer |
| actor | Whoever holds a role: an agent or a person |
| character | Who an actor is, in its own words: its standing prompt, kept in its config |
| direction | What a run of an actor is asked to do: given when it's performed |
| system | troupe acting by itself, recorded as an actor of kind `system`. It's how lineage will show a change troupe observed, such as a merge, once troupe records them |
| cast | The actors assigned to a performance |
| performance | One run of your process: every `troupe perform` records one, and each of its steps is a run |
| rehearsal | A dry run: any command that changes something, run with --rehearse, checks everything, shows what it would do, and changes nothing |
| audition | What troupe init --audition writes: a working example actor, Claude Code by default, ready to perform or edit. Not a rehearsal, which is a dry run (--rehearse) |
| stage | Where an actor runs: on the host, in a container, or elsewhere |
| runner | What runs an agent for an actor, named in the actor's config, such as claude-code or ollama. Some come with troupe, and others as extras of troupe-run |
| runtime | The service a runner talks to, or for an in-process runner the model file it loads: where it is, which model, and the variable its key is in, never the key itself. troupe has built-in ones, and config can define more |
| engine | What runs the model itself, such as Claude's API, Ollama or mistral.rs. A runtime says how a runner reaches one |
| notes | What a run teaches, fed into the next one |
| gate | A point where work waits for a decision from whoever owns it. Every run that works in its own worktree and succeeds with changes passes one when it ends |
| approver | A role that may let a run's work through its gate. An actor lists its approvers in order: troupe, which keeps clean work by itself, then director, the role whoever runs troupe holds |
| escalation | How an agent gets a decision: research first, then a brief to the right person |
| cue | An open request to a role, with a brief. A gate raises one, and so does an escalation that can't resolve itself. The name is provisional |
| lineage | The record of who made each change, who approved it, and when |
| guest | An installable pack that adds to troupe |
| the house | The long-lived local process that runs troupe on your machine |
