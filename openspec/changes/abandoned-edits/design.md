# Design

## Context

Since the hand-edit sweep (#119, archived `2026-11-22-hand-edit-sweep`), every command that uses config sweeps the
files first (`core/config/sweep.py`, `syncing.py`). Each edited file becomes its own `Config.Changed` by the
`unknown` actor, `via: file`, with `vcs.source` naming the file. A sweep's changes share one change id, apart from
the command's own (D7 there). A `git restore` is read as a hand edit back (owner decision 1 on #119).

What exists to build on:

- Config is one stream (`config` spec, "One stream per theatre"). Each event names the previous heads as its
  parents. A settling event joins a fork. `merge.Merged.changes` lists every `Config.Changed` with its change id,
  actor, entries and files.
- Each session (each CLI command, pre-house) appends to its own segment, `events/<session>.jsonl`, created on its
  first record. One command's sweep changes and its own change are one batch in that segment.
- `Run.Started` names the config heads it ran under (`config`, sorted ids).
- `Vcs.committed_under` gives every file in HEAD or the index. The text store already uses it for visibility.
- The store already rebuilds its local order, and restarts followers, when an event file disappears (event-store,
  "The local order rebuilds itself when events disappear").

The owner's decisions (2026-11-23, on #45) set the behaviour: values back means abandoned, whoever made the
changes. Drop is offered only while safe, and is otherwise kept with a reason. The question is a notice plus
`config drop`/`config keep`. No answer keeps it, and sync repeats the notice.

## Goals / Non-Goals

**Goals:**
- Find the round trip a sweep's edits close, from events alone.
- Say whether it can be dropped, and if not, exactly why.
- Drop it without rewriting git, without leaving a missing parent or a run's config version dangling, and without
  touching anything but whole uncommitted segments.
- One path for every surface: protocol commands, a shared notice.

**Non-Goals:**
- Hiding committed round trips (no marker event; owner, Q2).
- Classifying stashes (#1).
- Round trips that span a settle (a merge of branches): not looked for (D2).
- A hand move and back (#138).

## Decisions

### D1. The round trip a sweep closes

A **round trip** is identified by the change id of the sweep that closed it (its *closing change*). It holds:

- `events`: the config events from its first change `X` to the closing sweep's last event, in chain order;
- `files`: the files whose values went back (each sweep edit that closes it);
- `changes`: the change ids of those events, in order.

For one sweep edit `Y` of file `F`, the file's **scope** is the part of config `F` owns (hand-edit-sweep D2):
- an actor's `.yaml`, every field of `actors.<name>` except `character`;
- an actor's `.md`, `actors.<name>.character`;
- a runtime's `.yaml`, `runtimes.<name>`;
- an edit removing an actor whole (`.yaml` and `.md` deleted together), the whole group `actors.<name>`.

`Y` closes a round trip when there is an earlier event `X` in the linear tail (D2) such that `F`'s scope in the
config just before `X` equals `F`'s scope just after `Y`. The comparison is by values (canonical JSON), so comments
and formatting never matter, and an absent group equals an absent group. Of the events that qualify, `X` is the
latest one, so the round trip is the shortest: 3 → 5 → 3 → 5 → 3 closes only the last 5 → 3. Then:
- several steps count (3 → 5 → 7 → 3 is one round trip of three changes);
- a partial undo doesn't (the scope isn't equal);
- `X` can be anyone's change, a `troupe config set` included (owner, Q1).

**One sweep, one round trip.** When several of one sweep's edits close round trips, they are one round trip: from
the earliest `X` among them, with every closing file. That covers an actor deleted and restored, whose `.md` and
`.yaml` come back as two edits in one sweep. A closing file counts only if it's back, at that earliest `X`, to what it holds
after the sweep. A file whose own round trip began later isn't, so it's left out of `files`, and the changes to it
in between are outside the round trip's files: `changes-more`, never dropped while the file still holds them (found
by an independent review on #504: dropping them deleted a person's `config set` the `.md` still held).

The function is `round_trip(history, closing) -> RoundTrip | None`, in a new module `core/config/abandoned.py`. It
replays the tail forward with `changes.apply`, from the config at the start of the tail, so it costs one pass. It
never asks git.

Rejected: matching `vcs.source` hashes. `before` is the hash of the file config rendered, not of the bytes the person
had (hand-edit-sweep D7), so a restore of a hand-formatted file never matches. The owner chose values (Q1).

### D2. Only the linear tail since the last settle

The search runs over the config stream's events after its last settling event (or from the start), which on the
current branch form one chain once the sweep has recorded. A sweep on a forked stream settles it in the same batch
(hand-edit-sweep D7), so its edits are always on that tail. A round trip that would reach back past a settle isn't
looked for. Those events come from a merge of branches, and are committed, so they could never be dropped anyway.

### D3. When a round trip can be dropped

`blocked(store, trip, *, runs_now=False) -> Blocked | None` says why not, or None when it's safe (`referred` is its
steps 2 and 3, which a drop re-checks under the store's lock). It checks, in this
order, and the first that fails is the reason:

1. **`changes-more`**: an event in the round trip changes a value outside the closing files' scopes, such as a
   `config set` of two actors, or another file edited in between. Dropping it would undo more than the files.
2. **`built-on`**: a config event outside the round trip names one of its events as a parent, such as the command's
   own change recorded with the closing sweep, or a later `config set`. Details name that change.
3. **`run`**: a recorded `Run.Started` names one of its events among its config heads, or `runs_now` says the command
   reporting it is about to start one (perform's sweep, D5). Details name the run, when there is one.
4. **`committed`**: a recording of one of its events is in a segment that is committed (in HEAD or the index).
5. **`shares-segment`**: a segment holding one of its events holds an event outside the round trip, of any stream,
   or an unfinished batch.

There's no "another branch" reason: an uncommitted segment of another branch is never read on this one (event-store,
"Uncommitted events from another branch are left out"), so its events are never part of a round trip here.

Order matters for the message: the reason a person can act on comes first. Steps 4 and 5 are the store's (D4).

So the drop is safe exactly when the round trip is the tail of the config stream, nothing refers to it, and its
events are alone in uncommitted segments of this branch. At most one round trip can be droppable at a time: the one
ending at the stream's head.

### D4. The store's drop

The port gains:

```python
def droppable(self, events: Sequence[str]) -> str | None: ...
def drop(self, events: Sequence[str], check: Callable[[], None]) -> tuple[Path, ...]: ...
```

- `droppable` returns `committed` or `shares-segment` if either holds for any recording of any of `events`, else
  None. It runs no git command beyond `committed_under` on the events directory, as visibility
  already does.
- `drop` takes the store's write lock, refreshes, and calls `check`, which raises to refuse. Under the same lock it
  runs `droppable`, refuses with `events.not-droppable` (naming the reason and each segment) if that fails, and
  refuses (reason `parent`) if any visible event outside `events` names one of them as a parent. An event that isn't
  visible is refused as `unknown-event`. Then it deletes each segment holding them, the one holding the latest event in the store's order first, and returns
  their paths.
  Deleting goes through the platform seam (`platform/files.py` gains `remove_file`, beside `remove_tree`), so
  Windows' sharing rules are handled in one place. If a deletion fails partway, the remaining segments are left, the
  error (reason `remove-failed`) names them, and the next read rebuilds the order. Since the latest go first, what's
  left is an earlier part of the round trip, whose parents are all still here (found by Claude's review on #504: in
  oldest-first order a failure left later events naming removed ones). The closing sweep is then gone, so the next
  sync reads the file back again and offers what's left as a new round trip.
- Afterwards the store's order is rebuilt on its next read, with the `events.order-rebuilt` notice and followers
  starting again, as when a file is removed by hand. That's expected, and the drop's result says so.

`check` is how core keeps runs out: holding the store's lock, no `Run.Started` can be recorded between the check and
the deletion. Core's `check` re-runs D3 steps 1 to 3 on a fresh read.

That closes only the drop's side. A perform reads config's heads in its sync, then records `Run.Started` naming them
later, after its lease, pid file and artifact. A drop landing in between would find no run yet, and the run would then
name events that are gone (found by an independent review on #504). So the other side is closed too: `insert` takes
`requires`, event ids that must still be here, checked holding the same write lock, and refuses with
`events.required-missing` (naming them) otherwise, writing nothing. `EventStore.record_with_lineage(s)` and
`Command.record` pass it through, and perform records its run's start requiring its config version. Whichever takes
the lock first wins: a drop before the start makes the perform refuse before its runner starts, with a fix saying to
run it again; a start before the drop makes the drop refuse with `run`.

Rejected: holding the config files' lock from perform's sync to its start. It would hold every config command up
while a worktree is planned, and a nested sync would take the lock twice.

The event-store spec's "Events are never classified or dropped" becomes "Events are never classified, and leave
only through a person's drop". The store still never decides what's abandoned. It only removes what it's told to,
and only whole segments.

Rejected:
- **Removing lines from a segment.** Segments are append-only, and another session's segment is never written.
- **Re-recording later events with new parents.** Their ids would change, and runs name config heads by id.

### D5. Reporting: `config.edit-abandoned`

`syncing.py`, after recording a sweep, calls `round_trip` with the sweep's change id. When it finds one that the
person hasn't kept (D7), it adds the notice:

- `problem`: `.troupe/actors/tester.yaml is back to what it was before change <first>: the 2 changes since can be
  dropped.` Or, when not droppable: `... they're kept, because <reason>.`
- `fix`: `troupe config drop <closing> removes them; troupe config keep <closing> keeps them and stops this
  notice.` Or, when not droppable: `Nothing to do: they stay in history.`
- `details`: `change` (the closing change id), `files`, `changes` (the round trip's change ids, in order),
  `droppable` (boolean), and when it isn't, `reason` (one of D3's five) with `blocker` (the change id, run id or
  segment that blocks it, when there is one).

A rehearsal records nothing, so it has no closing change and reports nothing about round trips.

**Perform.** `sync_files` passes `runs_now=True`, since the run it's about to start names the new heads. Its notice
says the round trip is kept because the run uses it, before the run starts. So a person who restores a file and
performs is told straight away, not offered a drop that the run would stop.

**Sync repeats it** (owner, Q4). Every `troupe sync`, whatever it recorded, looks at the config stream's head. When
the head is the last event of a sweep (actor `unknown`, `via: file`), it runs `round_trip` with that sweep's change
id. If that's droppable and not kept, the notice is reported again. Nothing is reported for a round trip that can no
longer be dropped, so the reminder stops by itself once the person commits, performs or changes config. Other
commands report only a round trip their own sweep closed.

The notice is catalogued in `protocol/notice.schema.json`, with its details closed.

### D6. `config-drop` and `config-keep`

Both are client-protocol commands. Requests are `{change, rehearse?}` and `{change}`, closed. `change` is a change
id, as notices and `config get` show it.

**config-drop** holds the config files' lock (so no sweep runs meanwhile), then:
1. reads the stream, and finds the round trip whose closing change is `change`. None: refused with
   `config.no-round-trip`, naming the change, and saying `troupe config get` and the notice show change ids;
2. runs D3; a reason: refused with `config.round-trip-kept`, naming the reason and the blocker. Nothing is dropped;
3. kept already (D7): dropping still goes ahead, because the person asked now. The keep record loses the entry;
4. with `rehearse`, returns what it would drop and stops;
5. calls the store's `drop`, with `check` re-running D3 steps 1 to 3.

The result: `change`, `changes` (the change ids dropped), `segments` (the event files removed, theatre-relative),
`rehearsed`, and notices (the store's rebuild notice). The config files aren't written.
They already hold the values config goes back to, and the next sweep reads them as in line (values equal, so no
entries; hand-edit-sweep D9).

**config-keep** finds the round trip the same way (refusing `config.no-round-trip` likewise), then records the
closing change id in the keep record, and returns `{change, rehearsed, notices}`. Keeping a round trip that can't be dropped
anyway is allowed, and changes nothing but the record. Repeating a keep is a no-op. It takes `rehearse` too, as every
command that writes a file does (cli spec, #137).

New error codes: `config.no-round-trip`, `config.round-trip-kept`, `events.not-droppable` (the store's own,
which `config.round-trip-kept` normally pre-empts), and `events.required-missing` (D4). Each lands with code that raises it and a test (protocol_guard).

### D7. The keep record

`.troupe/local/config/kept.json`, clone-local and out of git like `present.json`: a JSON list of closing change ids,
sorted. It's about this clone's uncommitted events, so it doesn't travel.
- Absent: none kept.
- Unreadable (not JSON, or not a list of strings): counted as none kept, so the notice reappears, which can't lose
  data. A notice `config.kept-unreadable` names the file, and the next keep rewrites it.
- Entries for round trips that no longer exist are harmless. A keep drops entries whose change is no longer in the
  stream, so the file doesn't grow.

### D8. CLI

`troupe config drop <change> [--rehearse]` and `troupe config keep <change> [--rehearse]`, in `cli/config.py`, each
one protocol call. Rendering:
- drop: `Dropped 2 changes (<ids>): removed .troupe/events/<a>.jsonl, .troupe/events/<b>.jsonl.` A rehearsal says
  `Would drop`, and exits with the "would change" code.
- keep: `Kept the changes of <change>; troupe won't ask about them again.`
- Refusals render from the structured error, as every error does. `config.round-trip-kept` and `config.no-round-trip`
  exit 1 (failure), as `errors.CODES` says.

The notice renders like every notice, on standard error.

### D9. Docs

`docs/stagecraft/hand-edit-config.md` gains "Undoing an edit": what's recorded, the notice, drop and keep, when a
drop is refused and why. `docs/prompt-book/cli.md` lists the two commands. `contributing/config.md` names
`abandoned.py` and the store's drop. The protocol CHANGELOG and version come from release-please, through the commits' types (`feat(protocol)`, `feat(config)`); nobody edits them by hand.

## Risks / Trade-offs

- **Drop is narrow.** Most round trips that pass through a `troupe perform` or a `config set` are kept, by design:
  a run used them, or a change builds on them. The notice says so, which is the point. A person who wants them gone
  from a branch's history can still squash before pushing; troupe doesn't do it for them.
- **A stash looks like a restore** (#1). Dropping after `git stash` and then running `git stash pop` records the edit
  again as a new hand edit. Nothing is lost, because the file holds it.
- **Followers restart** after a drop, as after any removed event file. Pre-house that's the CLI's own projections.
  Once there's a house, it rebuilds them.
- **A deletion that fails partway** (a file locked on Windows by an indexer, say) leaves some segments. The error
  names them and the order rebuilds. Removing the latest first leaves an earlier part of the round trip, so no event
  is left with a missing parent; nothing is lost, because the file holds the values.
- **#138 (config mv)** also changes `syncing.py`. This change adds one call after recording and one parameter, so
  a rebase should be mechanical. A rename and back is #138's.

## Migration Plan

Pre-1.0, additive: two new protocol commands, two notices, four error codes. No event changes shape. No
infrastructure Purpose change, since no spec is added or removed and no Purpose is edited.

## Open Questions

None. The owner settled Q1 to Q4 on 2026-11-23. Anything the build finds that changes behaviour goes back through
the orchestrator before the code depends on it.
