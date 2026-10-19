---
title: Lineage
description: Who did what, and when.
status: written
prerelease: true
---

Lineage is the record of where each change came from. Every event troupe records carries it, so any part of your
theatre's history can answer: who did this, through what, when, why, as part of what, and with whose approval?

## What lineage says

- **`actor`:** who made the change: a person (`human`) or an agent (`agent`), with an id and where the id came
  from. It's never empty. Where nobody can be known, such as a hand edit to a file, it says so explicitly
  (`unknown`) rather than guessing.
- **`via`:** the surface it came through: the command line (`cli`), a file, a runner, or the run server.
- **`at`:** when troupe recorded it, in UTC.
- **`reason`:** why, in the actor's own words, when one was given.
- **`change`:** the id of the command that started it. Every event that follows from one command carries the same
  change id, including events recorded in reaction to it, so you can gather everything one command caused.
- **`cause`:** what made it happen: the command itself, or the event it reacted to.
- **`approvals`:** who approved it, and in which role. It's empty until gates exist.
- **`vcs`:** the version-control state it was made in: the branch and commit, and for a change made from a file,
  the file and its contents before and after, by hash.
- **`stage`:** for an event a run recorded, the stage the actor ran on, whether troupe could enforce what it
  touched, and if not, the policy setting that allowed it to run.

The [events reference](../prompt-book/events.md#lineage) lists every field, generated from its schema.

## Who the actor is

troupe works out who you are from a chain of sources, in order, and the first that answers wins:

1. **`TROUPE_ACTOR`,** as `human:<id>` or `agent:<id>`, if it's set.
2. **Your git identity:** git's `user.email`, with a repository's own setting winning over the global one, as in
   git.
3. **Your login name** on the computer.

If none answers, the command fails before anything is recorded: troupe never records a guess. A source that finds
something it can't use cleanly fails the command too, rather than passing on to the next source and quietly
recording the wrong person: `TROUPE_ACTOR` set to anything else, or two `user.email` values in one git
configuration. Lineage records which source answered.

When troupe runs an agent, troupe gives it its identity, from the actor it runs. The agent never claims one.

## Large things are referenced, not copied

A run's transcript, its instructions and the runner's options can be large, or hold what shouldn't be in git, such
as secrets an actor's tools read. troupe keeps them out of git, in the theatre's own store, and lineage refers to
each by the SHA-256 hash of its contents. The same contents always get the same reference, and reading one checks
it still matches.

## What comes next

- **Roles.** Work will go to roles, and lineage will record which holder acted and in which role
  ([#61](https://github.com/troupe-run/troupe/issues/61)). How a raw identity, such as an email address, maps to a
  person is open in [#44](https://github.com/troupe-run/troupe/issues/44).
- **Approvals.** `approvals` fills in once [gates](gates-and-decisions.md) exist.
- **troupe acting by itself.** When troupe observes a change, such as a merge, it will record it as an actor of
  kind `system`. That kind is decided, but troupe doesn't record it yet.

[Read the lineage](../stagecraft/read-the-lineage.md) shows how to answer questions from it.
