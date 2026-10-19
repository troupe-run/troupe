---
title: Configure roles and people
description: Setting up roles.
status: written
prerelease: true
---

This page will show how to define the roles in your process and assign agents and people to them. Roles aren't built
yet ([#61](https://github.com/troupe-run/troupe/issues/61)), and how they're written in config isn't decided. This is
what is.

## What's decided

- **Work goes to roles,** not to people or agents. [Gates](../the-company/gates-and-decisions.md) and
  [escalations](../the-company/escalation.md) are addressed to a role, and whoever holds it picks them up.
- **Config says who holds which role,** people and agents alike.
- **Lineage records which holder acted, and in which role.**
- **An agent's identity comes from its actor.** troupe gives an agent its identity from the actor it runs, so an
  agent never claims to be someone.
- **An actor is defined in its own file,** named for it: `actors/tester.yaml`, with `actors/tester.md` for its
  prompt ([#60](https://github.com/troupe-run/troupe/issues/60)).

## Who you are, today

Until roles exist, troupe records the raw identity of whoever acts, from the first of these that answers:

1. `TROUPE_ACTOR`, set to `human:<id>` or `agent:<id>`;
2. your git `user.email`;
3. your login name on the computer.

If none answers, or one is set but can't be used cleanly, the command fails rather than guessing. See
[Lineage](../the-company/lineage.md#who-the-actor-is).

## Not decided yet

The same person can arrive as different ids: a git email on one computer, a login name in a container,
`TROUPE_ACTOR` in CI. How config maps those ids to one person is open in
[#44](https://github.com/troupe-run/troupe/issues/44). Who holds which role, and how that's written in config, is
part of [#61](https://github.com/troupe-run/troupe/issues/61).
