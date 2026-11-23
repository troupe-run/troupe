# Proposal

## Why

Since the hand-edit sweep (#119, #490), undoing an edit with `git restore` is recorded as a hand edit back, so
history reads 3 → 5 → 3. The only way to drop the round trip is to delete untracked event files by hand, and a later
event can depend on them (a missing parent is refused). #1 named keep-and-ask as a later addition, and #119's owner
decision said #45 would offer to drop the round trip. Issue: troupe-run/troupe#45. The owner settled its four
questions on 2026-11-23, recorded in the issue body.

## What Changes

- **Seeing an abandoned edit.** After a sweep records hand edits, troupe works out from the config stream whether
  any edited file's values are back to what they were before an earlier run of recorded changes to that file,
  whoever made those changes (a `troupe config set` undone by `git restore` counts). Comments and formatting don't
  matter, several steps count, and a partial undo doesn't. Stashes aren't classified, and git isn't asked about
  them.
- **Saying so.** The command whose sweep records the edit back reports the notice `config.edit-abandoned`. It names
  the files, the changes in the round trip, and whether they can be dropped, and if they can't, why: committed, a
  run used them, a later change builds on them, they share a segment with other events, or they change more than
  the files.
- **Answering.** `troupe config drop <change>` removes the round trip's events. `troupe config keep <change>` stops
  troupe asking. Both are client-protocol commands (`config-drop`, `config-keep`) with `--rehearse`. troupe never
  prompts.
- **Dropping only while it's safe.** Every event in the round trip must be in an uncommitted segment on the current
  branch that holds nothing else, and nothing may be recorded on top of it: no later config change, and no run under
  that config. Then the drop deletes those segments, and nothing in git is rewritten. Otherwise the drop is refused,
  naming why.
- **No answer keeps it.** `troupe sync` repeats the notice while the round trip can still be dropped. Other commands
  don't. A keep is recorded in this clone only, out of git.
- **The event store gains a drop**, which removes whole uncommitted segments and refuses anything else. Events are
  still never classified by the store, and are kept unless a person drops them.
- Docs: `docs/stagecraft/hand-edit-config.md` (undoing an edit), the CLI reference, `contributing/config.md` and
  `contributing/event-store.md`. The protocol CHANGELOG comes from the commits (two new commands, two notices, three
  error codes).

Out of scope: changing the default (an unanswered round trip is kept), classifying stashes, rewriting git or
committed events, hiding round trips with a marker event, and a hand move going back and forth (#138).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `config-hand-edits`: abandoned edits are seen, reported, and kept or dropped.
- `event-store`: a person's drop of whole uncommitted segments is the one way an event leaves the store. The store
  still never classifies.
- `client-protocol`: `config-drop` and `config-keep` are protocol commands.
- `cli`: `troupe config drop` and `troupe config keep`.

## Impact

- `packages/troupe/src/troupe/core/config/`: a new module for round trips (detection, safety, keep record).
  `syncing.py` reports the notice. `commands.py` gets the two methods.
- `packages/troupe/src/troupe/core/events/port.py`: the store's drop. `troupe-store-text` implements
  it.
- `packages/troupe/src/troupe/protocol/`: `client/config-{drop,keep}-{request,update,result}.schema.json`, the
  notices `config.edit-abandoned` and `config.kept-unreadable`, and error codes.
- `packages/troupe/src/troupe/cli/`: the two subcommands and their rendering.
- `syncing.py` is also touched by #138 (config mv), which is in progress. Whichever merges second rebases.
