---
title: Roles and actors
description: Roles, and who holds them.
status: written
prerelease: true
---

A **role** is a job in your process, such as product owner, engineer or reviewer. An **actor** is whoever holds a
role: an agent or a person. Agents and people hold roles the same way, so your process doesn't change when a person
takes over from an agent, or an agent from a person.

## Actors today

Roles aren't built yet, but actors are. `troupe perform <actor>` runs an actor by name, and every event troupe
records names the actor that made it, in its [lineage](lineage.md):

- **A person** (`human`), identified by `TROUPE_ACTOR`, your git email or your login name, in that order.
- **An agent** (`agent`). troupe gives an agent its identity from the actor it runs: the agent never claims one.
- **Nobody knowable** (`unknown`), such as a hand edit to a file. troupe says so explicitly rather than guessing.

## Roles, when they come

This is decided, and not yet built ([#61](https://github.com/troupe-run/troupe/issues/61)):

- **Work goes to roles,** never to "the human" or a particular agent. [Gates](gates-and-decisions.md) and
  [escalations](escalation.md) are addressed to a role, and whoever holds it, a person or an agent, picks them up.
- **Config says who holds which role,** people and agents alike.
- **Lineage records which holder acted, and in which role.**
- **troupe can act by itself,** recorded as an actor of kind `system`: that's how lineage will show a change troupe
  observed, such as a merge.
- **An actor's config lives in its own file,** named for it: `actors/tester.yaml`, with `actors/tester.md` for its
  prompt, is the actor `tester` ([#60](https://github.com/troupe-run/troupe/issues/60)).

The same person can arrive as different ids: a git email on one computer, a login name in a container,
`TROUPE_ACTOR` in CI. How those map to one person isn't decided yet: it's open in
[#44](https://github.com/troupe-run/troupe/issues/44).

The [cast](../prompt-book/glossary.md) is the actors assigned to a performance. [Configure roles and
people](../stagecraft/configure-roles.md) says more about setting roles up.
