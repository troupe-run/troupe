# Proposal

## Why

When two branches change the same actor, git merges their config events cleanly, since each session appends to its
own segment. But it merges the actor's projected files, `.troupe/actors/<name>.yaml` and `.md`, as text. When it
can't combine their lines, it leaves conflict markers in the file. troupe then treats the file as one a person wrote
and refuses to replace it, including from the `troupe config set` that would resolve the config conflict. Today the
refusal tells the person to take one side with `git checkout --ours` and run troupe again (#141). That's a manual step
on a file nobody wrote by hand, and it happens on every config conflict, and also on merges where config itself
merges cleanly.

A second case, found while deciding #141, hits the same refusal. git can merge a file's lines cleanly while config
doesn't merge: two branches edit different paragraphs of one character, which config treats as one value (#135).
git commits the merge with the combined text, and troupe refuses that file too, because it isn't a version troupe
wrote.

## What Changes

- **troupe recognises a config file that git merged from its own versions** (owner, 2026-10-23: "recognise it",
  the first option on #141). A file counts as troupe's, and can be replaced, when:
  - **git left it conflicted:** git's index shows the path unmerged, and each side present (ours, theirs) is a
    version troupe recorded. It doesn't matter what the working file holds: markers, one side, or a resolution
    the person started by hand.
  - **git merged it cleanly:** a merge is in progress, or HEAD is the merge commit. The working file is exactly what
    git merged, git reproduces it as the clean merge of the sides, and each side is a version troupe recorded.

  If any side isn't troupe's, the file is refused as it is today.
- **A recognised file is rewritten from the merged config,** which is worked out from both branches' events. So the
  file says what the merge says, not what either side said.
- **Only an explicit command rewrites a recognised file** (owner, 2026-10-23): `troupe flush`, or the `troupe config
  set` whose own change writes that file. Every other command that uses config refuses with
  `config.file-not-troupes`. That includes `perform`, and a `config set` of an unrelated value. (Commands that only read, such as
  `status` and `config get`, don't flush, so they neither rewrite nor refuse it.) The refusal
  says the file is a merge of troupe's own versions, and that `troupe flush` rewrites it from the merged config and
  keeps a copy. So a file someone is part-way through resolving in their editor never changes under them.
- **troupe keeps a copy of the file before replacing it** (owner, 2026-10-23). Its bytes go into the artifact store,
  as `troupe flush --force` does, and the new notice `config.merge-rewritten` names the file, why it counted as
  troupe's, and the hash its bytes were kept under. So nothing is lost, even a half-done resolution by hand.
- **troupe leaves git's index alone** (owner, 2026-10-23). The notice says to `git add` the file and commit the
  merge. Marking the path resolved automatically, behind a setting that's off by default, is #156.
- **The VCS port gains one query:** a path's merge sides. The git adapter reads them from the index's stages during
  a conflict, or from the merge's parents for a clean merge. The plain-filesystem adapter never reports any.
- **The refusal for a conflicted file changes.** It's given only when a side isn't troupe's, and it says which side.
  The docs' manual steps for #141 are replaced by what now happens.

Out of scope:
- changing git's index, or committing the merge (#156);
- a git merge driver or `merge=` attribute for `.troupe/actors/**` (considered on #141 and not chosen);
- merges older than HEAD: a merge commit with commits after it gets today's refusal, and its fix;
- reading hand edits back into config (#119).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `config-files`: "Only a file troupe wrote is replaced" also accepts a file git merged from troupe's versions,
  conflicted or clean. Two new requirements: such a file is rewritten from the merged config, with its bytes kept
  and a `config.merge-rewritten` notice, and only `troupe flush` or the `config set` that writes it may rewrite it. The conflicted-file scenario changes.
- `vcs`: The port reports a path's merge sides. The git adapter reads them from the index during a conflict, or from
  the merge's parents when git merged cleanly. The plain-filesystem adapter reports none.

## Impact

- `packages/troupe/src/troupe/core/vcs.py`: a `MergeSides` type and the `merge_sides` query on the `Vcs` protocol.
- `packages/troupe-vcs-git`: the query, using `git ls-files --unmerged`, `MERGE_HEAD`, HEAD's parents,
  and `git merge-tree --write-tree`. `packages/troupe-vcs-files`: an empty answer.
- `packages/troupe/src/troupe/core/config/projection.py`: `plan` takes merge sides, and recognised files are
  replaced with a copy kept. `refuse` gets the new message.
- `packages/troupe/src/troupe/core/config/commands.py`: `config set`, `flush` and the flush every command runs first
  pass the merge sides in, and say which paths each may rewrite.
- `packages/troupe/src/troupe/core/notices.py` and `protocol/schemas/notice.schema.json` (with the copy bundled in
  the package): the `config.merge-rewritten` notice and its details.
- Docs: `docs/stagecraft/hand-edit-config.md` (Branches) and `contributing/config.md`.
- Issues: closes #141. #156 follows on from it.
