# Design

## Context

The name contest (`entities.py`, `Entities.named`) contests each key's births, renames and removals once, over all of
its writes, and then replays the writes it didn't drop, in arrival order, to get each key's name (`_replay`). Then it
settles clashes (`_clashes`, `_settle`). When two keys' claims to one name are concurrent, the claiming renames go into
`dropped` and those keys fall back. `_replay` runs again with the larger `dropped`.

The contest only drops writes on concurrent lines. Writes covered by a later write on every line are left alone,
because the later write decides. When a clash drops that later write, the writes beneath it can be concurrent and
undecided. `_replay` applies them in arrival order, so the last to arrive gives the name. Hence #532.

## Goals / Non-Goals

**Goals:** a key that falls back gets the name its remaining writes contest to, the same in every order. Histories
with no fallback merge exactly as before.

**Non-Goals:**
- Reporting the conflict the fallback uncovers (here the removal against the rename to qa) as a second conflict. The
  clash is already reported, and resolving it decides the entity's name. Today neither order reports it either, so
  the conflicts don't change.
- Changing the value contest. Values never see rename entries, and the removal is already left out of value replay
  (`_kept_by_a_rename`), the same in both orders.

## Decisions

- **D1: contest a fallen-back key's remaining writes again, in `_settle`.** Straight after a clash adds a key's
  claiming renames to `dropped`, run `_contest` over that key's writes still in play (within the events, not dropped)
  and add what it drops. `_contest` already goes down a round while no latest write stays in, as the value contest
  does (#190). This is the name-contest version of what `merge._contests` does for values (#503): a point whose
  covering writes lost one is contested again without it.
  - *Alternative: contest every key again on every `_replay`.* That could change histories with no clash, since the
    first contest's leftovers (agreeing concurrent writes) would be re-run. Only keys that lost a write need it.
  - *Alternative: break ties in `_replay` by event id.* That would be the same in every order, but arbitrary. The
    rules say concurrent lines that differ conflict, and the history before them decides.
- **D2: what the found history should give.** After the fallback, reviewer's removal and rename to qa conflict (a
  rename against a removal), so both lines drop and reviewer keeps the name it was born with. Its values are the
  base's plus the character set on the line that didn't rename it. So config has qa (the old tester, character A),
  reviewer (character A) and the new tester, with the clash on tester. This follows "a rename and a removal conflict
  and leave the actor as it was" and "a rename onto a name another branch made conflicts on that name, and the renamed
  actor keeps its old name".

## Risks / Trade-offs

- [The re-contest could drop a removal on a reported conflict's losing side that should also leave value replay] → In
  #532 the removal is already left out of value replay by `_kept_by_a_rename`. The order property over generated
  histories (500 examples) and the existing rename tests check that nothing else moves.
