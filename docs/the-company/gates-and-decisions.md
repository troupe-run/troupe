---
title: Gates and decisions
description: Where work waits for a person.
status: written
prerelease: true
---

A **gate** is a point where work waits for a decision from whoever owns it. Gates aren't built yet
([#62](https://github.com/troupe-run/troupe/issues/62)). This is what's decided about them.

## Decisions go to roles

- **A gate is addressed to a role,** never to "the human" or to a particular person. Whoever holds the role, a
  person or an agent, picks it up. So when someone else takes the role over, decisions follow them without your
  process changing. See [Roles and actors](roles-and-actors.md).
- **A gate raises a cue:** an open request to a role, with a brief. An [escalation](escalation.md) that can't
  resolve itself raises one too. Notifications and the UI's inbox both show cues. ("Cue" is a provisional name.)
- **A [flow](flows.md) can stop at a gate** that needs a role's approval.
- **The answer is recorded with its lineage:** who answered, in which role, and when. It appears in the `approvals`
  of the events it approved, which stay empty until gates exist. See [Lineage](lineage.md).

## Nobody has to be watching

The [house](the-house.md) runs whether or not anyone's at a terminal, so a gate can reach whoever owns it as soon
as it's raised, not when someone happens to look.

## Across computers

The person who owns a decision may be working on another computer, with their own copy of the theatre. Nothing
about gates may only work for one person on one computer. How a request reaches them and how their answer comes
back, whether through git or another transport, isn't decided yet: it's open in
[#12](https://github.com/troupe-run/troupe/issues/12).

## Still open

How a gate is defined in your config, and who holds which role
([#61](https://github.com/troupe-run/troupe/issues/61)), aren't decided yet. [Route decisions to the right
person](../stagecraft/route-decisions.md) will cover setting them up.
