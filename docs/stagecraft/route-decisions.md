---
title: Route decisions to the right person
description: Sending decisions to owners.
status: written
prerelease: true
---

This page will show how to make sure each decision reaches the person who owns it. The pieces it needs, roles and
gates, aren't built yet. This is what's decided about routing.

## Decisions go to a role

- **Every decision is addressed to a role,** never to "the human" or a particular person. A
  [gate](../the-company/gates-and-decisions.md) raises a cue to its role, and so does an
  [escalation](../the-company/escalation.md) that can't resolve itself.
- **Whoever holds the role picks it up,** a person or an agent. So when someone else takes a role over, decisions
  follow them, and your process doesn't change. You route a decision by saying who holds its role.
- **Notifications and the UI's inbox show cues,** and the [house](../the-company/the-house.md) raises them whether
  or not anyone's at a terminal.
- **The answer is recorded with its lineage:** who answered, and in which role.

## Not decided yet

- How you say who holds a role in config ([#61](https://github.com/troupe-run/troupe/issues/61)), and how a person's
  ids map to them ([#44](https://github.com/troupe-run/troupe/issues/44)).
- How a gate is defined ([#62](https://github.com/troupe-run/troupe/issues/62)).
- How a request reaches someone working on another computer, and how their answer comes back
  ([#12](https://github.com/troupe-run/troupe/issues/12)).
- Which channels notify each role. The leaning is a notification port with channels per role, but it isn't decided
  ([#12](https://github.com/troupe-run/troupe/issues/12)).
