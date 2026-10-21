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
| system | troupe acting by itself, recorded as an actor of kind `system`. It's how lineage shows a change troupe observed, such as a merge |
| cast | The actors assigned to a performance |
| performance | One run of your process |
| rehearsal | A dry run: any command that changes something, run with --rehearse, checks everything, shows what it would do, and changes nothing |
| stage | Where an actor runs: on the host, in a container, or elsewhere |
| notes | What a run teaches, fed into the next one |
| gate | A point where work waits for a decision from whoever owns it |
| escalation | How an agent gets a decision: research first, then a brief to the right person |
| cue | An open request to a role, with a brief. A gate raises one, and so does an escalation that can't resolve itself. The name is provisional |
| lineage | The record of who made each change, who approved it, and when |
| guest | An installable pack that adds to troupe |
| the house | The long-lived local process that runs troupe on your machine |
