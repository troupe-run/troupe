# Proposal

Issue: #156. Follows #141 (`config-projection-conflicts`, archived 2026-10-23).

## Why

Since #141, when git leaves a config file conflicted and both sides are versions troupe wrote, `troupe flush` (or the
`config set` that writes it) rewrites the file from the merged config and keeps a copy. git still lists the path as
unmerged, though, so the person has to `git add` it before they can commit the merge. The notice
`config.merge-rewritten` tells them so. That last step adds nothing: troupe knows exactly which bytes it wrote and
that the path's sides were its own. #156 asks for troupe to mark the path resolved itself, the way `git add` would,
behind a setting that's off by default and that policy can forbid.

## What Changes

- **A settings seam.** troupe has policy settings but no other kind. This change adds one seam that every
  non-policy setting is read through. It's shaped like policy's: each setting has its default in
  `troupe.core.defaults`, and each value comes with its source. The one source above the default, for now, is the
  session's environment: `TROUPE_SETTING_` and the setting's name in capitals. A malformed value is
  `settings.invalid-value`, never a quiet default. Owner, 2026-10-30: the environment for now, until policy files
  (#71) and house config (#2) bring levels.
- **The setting `mark_merges_resolved`**, false by default. When it's true, each config file this command wrote or
  removed whose path git's index held unmerged is marked resolved in the index. troupe stages exactly the bytes it
  wrote, or the removal, so the person only has to commit the merge. Nothing else is staged: not a clean merge's
  file, not an unmerged path troupe didn't rewrite, not troupe's event segments.
- **The policy setting `allow_mark_merges_resolved`**, true by default. When it's false, troupe acts as if the setting
  were off: the file is still rewritten as it is today, the index is left alone, and the notice says that policy
  forbade marking it, naming the policy variable (owner, 2026-10-30).
- **A VCS port operation, `mark_resolved`.** The git adapter writes each path's stage-0 entry, or removes all its
  stages, but only while the index still holds that path unmerged with the sides the plan saw. The plain filesystem
  adapter has no index and marks nothing.
- **The notices say what happened to the index.** `config.merge-rewritten` gains a `resolved` detail. Its fix says to
  commit the merge when troupe marked the file. When it didn't, the fix says why (the setting is off, policy forbids
  it, the index changed, or git failed) and still says to `git add` it. `config.file-rewritten` records `resolved`
  when it marked an unmerged file it rewrote for another reason.
- **Docs.** The `#156` placeholder is removed from the notice's fix and from `docs/stagecraft/hand-edit-config.md`,
  and the setting, its policy and the settings seam are documented.

Out of scope, as #156 says: committing the merge, staging troupe's event segments, and turning the setting on by
default.

## Capabilities

### New Capabilities

- `settings`: the seam that non-policy settings are read through, with one named default each and a known source.
  For now the only source above the default is the session's environment. Its `cap:settings` label already exists.

### Modified Capabilities

- `config-files`: "A file git merged from troupe's versions is rewritten from the merged config" no longer says troupe
  never changes git's index. A new requirement says when a rewritten unmerged file is marked resolved, and how the
  setting, policy and notices decide and report it.
- `vcs`: the port can mark paths resolved. The git adapter does it only for paths still unmerged with the sides the
  caller saw, staging the given bytes. The plain filesystem adapter marks nothing.

## Impact

- `packages/troupe/src/troupe/core/`: a new `settings.py`, plus `defaults.py`, `policy.py`, `vcs.py` (`MergeSides`
  gains an opaque record of the index's stages, and a `mark_resolved` method with its result type), `config/projection.py` (`flush`,
  `execute`, notices) and `config/commands.py` (`flush_files`, `config_set`, `sync_files`).
- `packages/troupe-vcs-git/` (`merges.py`, the adapter) and `packages/troupe-vcs-files/`.
- `packages/troupe/src/troupe/protocol/notice.schema.json`: new details on two notices, and `settings.invalid-value`
  wherever error codes are listed.
- Docs: `docs/stagecraft/hand-edit-config.md`, `docs/the-company/performances-and-runs.md` (policy and settings
  tables), `contributing/config.md`, `contributing/runs.md`.
- troupe-run/infrastructure: the new `settings` spec's Purpose has to be recorded in `oob/troupe-spec-purposes.json`
  (an infrastructure issue, on the board), or the drift job fails after the merge.
- The default doesn't change behaviour: with the setting unset, every command does exactly what it does today, except
  that the notice's fix names the setting instead of `#156`.
