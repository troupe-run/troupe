# The event store

troupe's state is events, kept as text that git can merge. Every event says where it came from (its lineage), and
nothing in git is ever rewritten because of a merge. This page describes the store as built by the `event-store`
change (#35); the decisions behind it are #1 (layout, ordering, forks, abandoned edits), #9 (identity) and #37
(what runs in process).

Runs are recorded here by `troupe perform`: see [contributing/runs.md](runs.md).

## Layout

```
.troupe/
  .gitignore         "local/" (and config's ".*.troupe~"): git never sees this clone's own state
  .gitattributes     "events/** -text" (and config's "actors/** -text"): git never converts line endings
  events/            committed: one <session>.jsonl segment per session per branch
  local/             gitignored: this clone's own state
    .lock            the write lock
    order/           each branch's notification order
    issued/          each branch's highest notification id issued, kept apart from its order
    tracking/        each branch's follower positions
```

- **A session** is one opened store in one process: in practice, one troupe command. It writes its own segment,
  named by a ULID, and starts a new one if the branch changes, so no two sessions ever write the same file and
  branches never conflict over event files.
- **The git files hold troupe's patterns, and keep yours.** Whenever troupe writes into `.troupe/`, it appends any
  of its patterns that `.gitignore` or `.gitattributes` is missing, under a comment saying troupe added it and why,
  and never changes, moves or removes a line that's there (`troupe.core.theatre.GIT_FILES`). A troupe line you
  delete comes back on the next write, because troupe needs it.
- **Reads create nothing.** Directories and files are created on the first write. Reading a theatre's events never
  changes anything in `events/`; at most it writes this clone's order under `local/`.

## Records

A segment's first line is its header; every later line is one event. Lines are strict JSON
([`event-record.schema.json`](../protocol/schemas/event-record.schema.json)).

```json
{"format":1,"segment":{"branch":"main","protocol":"0.2.0","session":"01K7…","vcs":"git"}}
{"batch":{"id":"01K7…","index":0,"size":1},"format":1,"id":"sha256:9f2c…","parents":["sha256:41ab…"],"state":{"lineage":{…},"timestamp":"…","value":5},"stream":"6c1e…","stream_type":"uuid","topic":"troupe…:Counter.Set","version":3}
```

- **The header says who wrote the segment.** `session` is the session's id (also the file's name), `vcs` the
  version-control adapter, `branch` the branch it was written on (left out when there was none), and `protocol` the
  protocol version of the troupe that wrote it (`troupe --version` prints it). A header without a `protocol` is a
  malformed record.
- **Content-hash ids.** An event's `id` is the SHA-256 of what it changed: its stream, version, topic, parents and
  state, leaving out the state's `timestamp` and `lineage`. Two clones that make the same change agree on its id,
  whoever made it and wherever. When a merge brings the same event twice, both lines stay (nothing is rewritten),
  reads return the event once, and every recording's lineage stays readable.
- **Readable payloads.** troupe's own events are canonical JSON (sorted keys, no spaces), so their state is written
  inline and reads well in a diff. Any other payload (encrypted, compressed, or not canonical) is written as
  `state_b64`, so every payload reads back byte for byte.
- **Every payload has a schema.** Each topic troupe records has a closed schema for its payload in
  [`protocol/schemas/events/`](../protocol/schemas/events/), including the fields the event-sourcing library adds
  (`timestamp`, and `originator_topic` on a stream's first event). The event-record schema picks the payload's
  schema by topic; an inline payload under a topic troupe doesn't define doesn't validate, and troupe's own topics
  are never held as `state_b64`. Field names are as recorded.

  | Topic | Payload schema |
  |---|---|
  | `troupe.core.runs.aggregate:Run.Started` | [`events/run-started.schema.json`](../protocol/schemas/events/run-started.schema.json) |
  | `troupe.core.runs.aggregate:Run.WorktreeMade` | [`events/run-worktree-made.schema.json`](../protocol/schemas/events/run-worktree-made.schema.json) |
  | `troupe.core.runs.aggregate:Run.Reported` | [`events/run-reported.schema.json`](../protocol/schemas/events/run-reported.schema.json) |
  | `troupe.core.runs.aggregate:Run.Noticed` | [`events/run-noticed.schema.json`](../protocol/schemas/events/run-noticed.schema.json) |
  | `troupe.core.runs.aggregate:Run.Ended` | [`events/run-ended.schema.json`](../protocol/schemas/events/run-ended.schema.json) |
  | `troupe.core.runs.aggregate:Run.ChangesAccepted` | [`events/run-changes-accepted.schema.json`](../protocol/schemas/events/run-changes-accepted.schema.json) |
  | `troupe.core.runs.aggregate:Run.ChangesDiscarded` | [`events/run-changes-discarded.schema.json`](../protocol/schemas/events/run-changes-discarded.schema.json) |
  | `troupe.core.runs.aggregate:Run.GatePassed` | [`events/run-gate-passed.schema.json`](../protocol/schemas/events/run-gate-passed.schema.json) |
  | `troupe.core.runs.aggregate:Run.CueRaised` | [`events/run-cue-raised.schema.json`](../protocol/schemas/events/run-cue-raised.schema.json) |
  | `troupe.core.runs.aggregate:Run.ChangesRejected` | [`events/run-changes-rejected.schema.json`](../protocol/schemas/events/run-changes-rejected.schema.json) |
  | `troupe.core.config.aggregate:Config.Changed` | [`events/config-changed.schema.json`](../protocol/schemas/events/config-changed.schema.json) |
  | `troupe.core.config.aggregate:Config.Settled` | [`events/config-settled.schema.json`](../protocol/schemas/events/config-settled.schema.json) |
- **Batches are all or nothing.** A batch is written with one fsynced append, and each line names its batch. A
  write that was interrupted leaves an incomplete batch at the end of its segment; reads leave it out and report
  `events.incomplete-batch`. It never took effect.
- **Reading is strict.** A repeated key, `NaN` or `Infinity`, an id that doesn't match the line's content, or an
  unknown `format` is refused with the file and the line, never quietly accepted. The same goes for the files under
  `local/`, except that a torn last line there (an interrupted append) is trimmed.

## Ordering

The library's followers need notification ids: integers that never change once issued, and that a follower can read
on from. Each branch keeps its own order in `local/order/`, so nothing that orders events is ever in git. Ids are dense
from 1 until the order is rebuilt, and dense within each order after that; an id is never reused on a branch.

- **New events are appended.** Events that arrive by a merge or a pull get the next ids, in a fixed order:
  topological by parents, then by session, then by line. An id already issued always names the same event.
- **A removed event rebuilds the order.** If an ordered event is no longer here (its file was deleted, or a reset
  dropped it), the order is rebuilt under a new epoch and `events.order-rebuilt` says so. Follower positions from
  the old epoch no longer count, so every projection is rebuilt from the beginning. Nothing is lost: the order is
  derived from the events.
- **A rebuilt order never reuses an id.** It's numbered after the highest id ever issued on the branch, and its
  epoch line says where it starts (`{"epoch": ..., "after": n}`). So a follower that read ids under the old order,
  whether it records that position after the rebuild or is a live subscription that keeps its position in memory,
  reads on into the new order and is given all of it, whichever eventsourcing runner or thread it uses
  (troupe-run/troupe#454). Delivery stays at least once.
- **The highest id issued is kept apart from the order,** in `local/issued/<branch>.json` (`{"issued": n}`, written
  whole). It's raised ahead of the order in steps of `ORDER_ID_RESERVE` ids (one write per step, not one per
  insert), so a rebuild can leave a gap of up to that many ids. Deleting the order file, as its error message says
  to, renumbers after the mark; deleting the mark alone loses nothing, because the order still names its ids. A
  damaged mark can't be rebuilt from the events, so its error says how to mend it. If the mark and the order file
  are both deleted (or all of `local/`), ids start at 1 again: troupe's own followers' positions are in `local/`
  too and start again with it, but a projection that keeps its position elsewhere must be rebuilt by hand.
- **Any store numbers, under the lock, from the file as it is now.** A reader numbers events too (a pull brings
  events no local process recorded), so `troupe logs --follow` beside a run is a second numberer. Each store keeps
  the order and tracking files in memory, but before using them it reads what other stores appended since it last
  looked, and reads them again whole if they were rebuilt or repaired. Only a store holding the lock trims a torn
  last line: for any other, it may be an append in progress.
- **Damage from two numberers is mended.** Before troupe-run/troupe#450 was fixed, two stores could number the same
  events. A line repeating an id for the same event is dropped and the file rewritten under the same epoch
  (`events.order-repaired`; followers keep their place). A line that gives one id to two events, an event two ids,
  skips an id or starts a second epoch rebuilds the order (`events.order-rebuilt`, naming the line), and followers
  start again. A line that isn't valid JSON, or isn't an order line, is still refused (`events.malformed-record`).
- **Writers queue.** Within a process, calls queue on a lock; across processes, writers queue on
  `.troupe/local/.lock`, announcing a wait and giving up after the platform's lock timeout.

## Subscriptions

Anything that waits for new events (`troupe logs --follow`, and later the house's live projections and reactions)
subscribes to the store through the port's `listen` and `unlisten`. The guarantee is the port's: every new event
reaches a subscriber, whoever wrote it, as it's recorded, and the store says so when it can only poll. Subscribers
never see how a store learns of writes.

The text store meets it like this:

- **Writes in the same process** tell subscribers at once.
- **Other processes' writes, and segments git brings in** (`pull`, `merge`, `checkout`), are heard by watching
  `events/` through the platform ([contributing/platform.md](platform.md#watching)). Until `events/` exists, the store
  watches its nearest existing parent, and moves to `events/` once it appears. A wake costs one incremental read;
  while nothing changes, no segment is read.
- **When `events/` can't be watched,** the store looks for new events every `SUBSCRIBE_POLL_SECONDS` instead, and
  its notices include `events.subscription-polling` (reason `watch-refused`) for as long as it does.
- **A file system that accepts watches but doesn't deliver them** (some container bind mounts and network shares)
  can't be told apart when the watch is set up. So every `SUBSCRIBE_CHECK_SECONDS` a store with subscribers looks for
  itself. If it finds an event its watch didn't report, it delivers it, polls from then on, and gives the same notice
  (reason `watch-missed-write`).
- **What doesn't wake a subscriber:** a branch switch that changes no file in `events/`. It can change which
  uncommitted segments are visible, but nothing new was recorded; the next read or wake sees the new branch.

## Forks and settling

A stream appended to on two branches has two heads once they are merged. Loading it, or appending to it, is refused
with `events.stream-forked`, which names each head, its version and its file. troupe never picks a winner.

A **settling event** ends a fork. Its parents are every head (naming fewer is `events.settle-incomplete`), and it
carries the settled state, built by the library's snapshot mechanics. Loading a settled stream starts from the
settling event, so no event from either branch before it is applied. History keeps both branches. What the settled
state is belongs to the aggregate.

**An aggregate can merge its own forks.** Config does (config-model design D5): it never loads its stream, but reads
its whole `history`, both sides of any fork, and works out the merged state itself, so a merge of two branches'
config changes is read rather than refused, and reading it records nothing. Its next change settles the fork in the
same batch: `Command.record(events, settles=heads)` records a settling event first, whose parents are those heads,
and the events after it follow it. Settling events are content-addressed like any other, so two clones that settle
a fork to the same state record one event. Runs don't merge their forks: a run is written by one `perform` in one
clone, so a forked run is a fault, and loading it is refused. `history` refuses nothing, so an aggregate that reads
it checks that every parent is here itself, and refuses with `events.missing-parent` as `load` would.

## Visibility and abandoned edits

- **Committed events are always read**, whatever branch made them.
- **Uncommitted events made on another branch are left out.** Untracked event files travel with `git switch`. On
  any other branch they are left out of every read and every version check, and `events.other-branch` names the
  file and the branch it was made on. A staged file counts as committed.
- **Nothing is classified.** An edit and the edit that reverts it are both recorded, so history reads 3 → 5 → 3.
  Events around a `git stash` and `stash pop` are all kept. The store never decides what's abandoned: config does,
  and asks the person (`config.edit-abandoned`, [config.md](config.md#abandoned-edits)).
- **A person's drop is the only way an event leaves.** `drop(events, check)` removes the segments holding `events`,
  holding the write lock, the latest first, so a removal that fails partway (`remove-failed`) leaves an earlier part
  of them, whose events still read with every parent present. It runs `check` first (config's: no run or change has used them
  since), then refuses with `events.not-droppable` unless every recording of each event is in an uncommitted segment
  of this branch that holds nothing else (reason `committed` or `shares-segment`), and no other event follows one of
  them (`parent`). An event that isn't visible is `unknown-event`. Segments are only ever deleted whole, never
  rewritten. Afterwards the order rebuilds, with `events.order-rebuilt`, as when a file is removed by hand.
  `droppable(events)` answers the segment question without the lock. A batch that names events it doesn't follow (a run's start
  names its config version) passes them to `insert(..., requires=...)`, checked under the same lock, so it can't
  race a drop: it's refused with `events.required-missing` instead.
- **A missing parent is refused.** If an event names a parent that isn't here (its file was deleted by hand), reads
  of its stream fail with `events.missing-parent`, naming the file and the missing event, and saying to restore the
  removed file or remove the dependent one too. If the parent is only in another branch's uncommitted file, the
  error names that file.

## Lineage

Every event troupe records carries lineage ([`lineage.schema.json`](../protocol/schemas/lineage.schema.json)). An
event without valid lineage is refused before anything is written (`events.lineage-invalid`). A field with nothing to
say is left out, never written as `null`.

| Field | What it says |
|---|---|
| `actor` | `human` or `agent` with an id and the source that resolved it, `system` with an id naming troupe's component and host (`core@<host>`) and no source, or an explicit `{kind: unknown}` (for a hand edit). Always present. |
| `via` | `cli`, `file`, `runner` or `server` |
| `at` | When troupe recorded it, in UTC with milliseconds |
| `reason` | Why, in the actor's words. Left out when none was given |
| `change` | The correlation id: minted by a command, and carried by every event that follows from it |
| `cause` | `{kind: command, id: <change>}` for a command's own events, or `{kind: event, id: <id>}` for a reaction |
| `approvals` | Who approved it, in which role: one approval on the acceptance that keeps a run's work at a gate (troupe's, in role `troupe`, or a person's, in role `director`), and empty on every other event |
| `vcs` | The adapter; the branch, left out when HEAD is detached or the adapter has no branches; HEAD, left out before the first commit; and for an event made from a file, its theatre-relative path and its before and after content hashes, each left out when the file didn't exist or no longer does |
| `stage` | For an event a run recorded, the stage the actor ran on and whether its effects were `enforced` or `unenforced`; for an unenforced run, the policy setting and source that allowed it (`allowedBy`). Left out for every other event |

**Correlation and cause.** If a command records E1, and E2, E3 and E4 are recorded in reaction to E1, all four
carry the command's change id, and E2 to E4 name E1 as their cause. A reaction to E2 still carries the same change
id. A cause naming an event that isn't recorded here is refused (`events.cause-unknown`).

## Identity

Who is acting comes from a chain of identity sources (#9, agreed 2026-10-12). The default, `IDENTITY_CHAIN`, is:

1. **`env`:** `TROUPE_ACTOR`, as `human:<id>` or `agent:<id>`.
2. **`vcs`:** the identity the VCS is configured with: git's `user.email`, with a repository's setting overriding
   the global one, as in git.
3. **`os-login`:** the login name of the account troupe runs as.

If no source answers, the command fails (`identity.unresolved`) before anything is written. troupe never records an
`unknown` actor, an empty id or a guess in place of an identity.

**Absent passes on; malformed or ambiguous fails.** A source that finds nothing (an unset `TROUPE_ACTOR`, no
`user.email`) passes to the next. A source that finds something it can't use cleanly fails the command, and never
falls through to the next source, because that would quietly record the wrong person:

- `TROUPE_ACTOR` set to anything but `human:<id>` or `agent:<id>`: `identity.invalid-override`;
- two `user.email` values in one git configuration: `identity.ambiguous`;
- a chain naming a source that isn't installed: `identity.unknown-source`.

Lineage records which source answered. When troupe runs an agent, troupe assigns its identity (`source: troupe`);
the runner never claims one.

## Adapters

The store, the VCS and the identity sources are ports defined in `troupe.core`. Their bundled implementations ship
with troupe as their own packages and run in process (#37), found by name through entry point groups; `troupe` never
imports them.

| Port | Group | Bundled |
|---|---|---|
| Event store | `troupe.store` | `text` (`troupe-store-text`) |
| Version control | `troupe.vcs` | `git` (`troupe-vcs-git`), `files` (`troupe-vcs-files`: no branches, everything committed, no merges) |
| Identity sources | `troupe.identity` | `env`, `vcs`, `os-login` (`troupe-identity-local`) |

The text store is also an `eventsourcing` persistence module (`PERSISTENCE_MODULE=troupe_store_text`, with
`TROUPE_THEATRE` and `TROUPE_VCS`), and passes the library's own recorder test suite unmodified. The git adapter
runs git with its own environment policy ([contributing/platform.md](platform.md#the-git-adapter-troupe_vcs_gitdefaults)). Besides
the branch, HEAD and what's committed, the VCS port reports a path's merge sides, which config reads to recognise a
file git merged from troupe's own versions ([contributing/config.md](config.md#files-git-merged)).

## Notices and errors

Reads report conditions that aren't failures as notices: structured data with a code, the problem, the fix and the
path ([`notice.schema.json`](../protocol/schemas/notice.schema.json)).

| Notice | When |
|---|---|
| `events.other-branch` | Uncommitted events made on another branch were left out |
| `events.order-rebuilt` | An ordered event is no longer here, or the order gave one id to two events (or similar), so the order was rebuilt and followers start again |
| `events.order-repaired` | The order repeated lines (the same id for the same event); they were dropped, and followers keep their place |
| `events.incomplete-batch` | A segment ends in a batch whose write was interrupted; it was left out |
| `events.subscription-polling` | Subscribers can't be told of other writers' events as they're recorded, so the store looks for them every `SUBSCRIBE_POLL_SECONDS` |

| Error | When |
|---|---|
| `events.version-conflict` | Another change recorded the same version first |
| `events.stream-forked` | A stream has two heads and hasn't been settled |
| `events.settle-incomplete` | A settling event doesn't name every head |
| `events.missing-parent` | An event's parent isn't here |
| `events.not-droppable` | A person's drop can't remove those events whole |
| `events.required-missing` | A batch needs events that aren't here any more, such as a run's config version a person dropped since the run read it |
| `events.malformed-record` | A line of a segment, or of a local file, isn't valid |
| `events.unknown-format` | A line uses a record format this troupe doesn't read |
| `events.lineage-invalid` | An event's lineage isn't valid |
| `events.cause-unknown` | A reaction names a cause that isn't recorded here |
| `events.unknown-store` | No event store of that name is installed |
| `events.subscription-not-stopped` | A stopped subscription's thread didn't end within `SUBSCRIBE_STOP_TIMEOUT_SECONDS` |
| `identity.unresolved` | No identity source answered |
| `identity.invalid-override` | `TROUPE_ACTOR` isn't `human:<id>` or `agent:<id>` |
| `identity.ambiguous` | A source found more than one identity |
| `identity.unknown-source` | The chain names a source that isn't installed |
| `vcs.unknown-adapter` | No VCS adapter of that name is installed |
| `vcs.failed` | A git command failed |
| `vcs.not-a-repository` | `troupe init` was run in a directory that isn't in a repository of the theatre's version control |
| `vcs.worktrees-unsupported` | The version-control adapter can't make a run's worktree (the plain filesystem adapter) |
| `vcs.short-name-undecided` | git's answers can't settle an unborn branch's short name: a name may be a ref at the top of the git directory while two other refs share it |

## File count

Each recording command adds one segment. Reading a theatre reads every segment, so the cost grows with the file
count. Measured with `uv run scripts/benchmark_event_store.py` (10,000 segments of one event each, on an Apple M1
Max, macOS, Python 3.12):

| Read | Time |
|---|---|
| First read in a clone (orders every event) | 1.7 s |
| Later read (order already written) | 1.5 s |

A long-lived session (the house, #5) writes far fewer segments. If the cost becomes a problem, a later change can
compact committed segments.

## Defaults

Every limit has its default in `troupe.core.defaults`, and each can be overridden by the caller. The store's write
lock uses the platform's lock defaults (`LOCK_TIMEOUT_SECONDS`, `LOCK_ANNOUNCE_AFTER_SECONDS`), and the identity
chain is `IDENTITY_CHAIN`. `SUBSCRIBE_POLL_SECONDS` is how often a subscription looks for new events when it can only
poll, and `SUBSCRIBE_CHECK_SECONDS` how often a store with subscribers checks that its watch is delivering.
`SUBSCRIBE_STOP_TIMEOUT_SECONDS` bounds how long stopping a subscription waits for its thread to end: once the stop
returns, the subscription neither reads nor writes the store. `ORDER_ID_RESERVE` is how far ahead of the order the
store raises its record of the highest notification id issued on a branch (see Ordering).

| Setting | Default |
|---|---|
| `SUBSCRIBE_POLL_SECONDS` | 1 |
| `SUBSCRIBE_CHECK_SECONDS` | 30 |
| `SUBSCRIBE_STOP_TIMEOUT_SECONDS` | 5 |
| `ORDER_ID_RESERVE` | 1024 |
