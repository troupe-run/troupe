# Design

## Context

See proposal.md for why. Since `config-projection-conflicts` (#141):

- `projection.plan` takes `merged: Mapping[str, MergeSides]` (from `merges(store.vcs)`) and `resolve`, the paths this
  command may rewrite from a merge. A recognised file becomes a `write`, `remove` or `finish` action with `keep=True`
  and `merge="conflicted" | "clean"`. A file whose bytes are already vouched for (recorded, or in `written.jsonl`)
  is rewritten under step 1 with no copy kept, even when git's index holds it unmerged. That's the "Removed on one
  side, changed on the other" case, and what happens after `git checkout --ours`.
- `execute` runs under the config lock, after the plan has been made again under that lock with the merges read
  again. It returns `kept`. `Flushed.notices()` and `merge_notices` build `config.file-rewritten` and
  `config.merge-rewritten`.
- `flush_files`, `config_set` (four plans) and `sync_files` are the three callers. Each has `session.env` and
  `store.vcs`.
- The VCS port is read-only for the theatre. The git adapter writes an index only in a run's own worktree.
- Policy is read through `troupe.core.policy.read_policy(env)`, with defaults in `troupe.core.defaults`. There's no
  seam for any other kind of setting.

Observed with git 2.56 in a scratch repository (2026-10-30):

- On a path with stages 1, 2 and 3, feeding `update-index --index-info` the line `<mode> <blob> 0\t<path>` leaves
  one stage-0 entry, and the merge commits with no `git add`. `update-index --force-remove -- <path>` drops every stage
  of a path.
- **`--index-info` reads paths relative to the repository's top level, whatever directory git runs in.** Run from a
  theatre in `sub/` with the path `f`, it added a new entry `f` and left `sub/f` unmerged. Command-line paths, as
  `ls-files` and `--force-remove` take them, are relative to the directory git runs in.

## Goals / Non-Goals

**Goals:**
- With the setting on, the merge #141 rewrites can be committed with no `git add`.
- The index never gets bytes troupe didn't write, or a path it didn't rewrite, and a side a person wrote is never
  resolved away.
- With the setting unset, every command behaves exactly as it does today. Only the notice's fix text changes.

**Non-Goals:**
- Marking an unmerged path troupe didn't need to rewrite, because the file already holds what config writes. The issue
  limits marking to the paths troupe rewrote. Making the path resolvable from `troupe flush` would mean a flush that
  writes nothing but changes the index, which deserves its own decision.
- Clean merges. Their index entry is already stage 0, and staging troupe's rewrite there would stage a change the
  person didn't ask for.
- Committing, or staging event segments (#156, "Out").
- Settings levels (project, user, house) and policy files. The seam is built so they slot in (#71, #2).

## Decisions

### D1. A settings seam beside policy's, read from the environment

`troupe/core/settings.py` mirrors `policy.py`: `ENV_PREFIX = "TROUPE_SETTING_"`, a `SettingFlag(setting, value,
source)`, a frozen `Settings` holding every setting, and `read_settings(env) -> Settings`, which raises
`settings.invalid-value` for anything other than `true`, `false`, unset or empty. Defaults go in `defaults.py` under a
"Settings" heading: `MARK_MERGES_RESOLVED = False`.

It's a separate seam rather than another policy flag because policy is authoritative and only tightens. A setting is
a person's preference, which policy bounds. Owner, 2026-10-30: the environment for now. The alternatives were a new
`settings` kind of config, recorded as events and travelling with the branch (a bigger change, and the setting would
merge like any config), and `git config troupe.markMergesResolved` (a troupe setting outside troupe's one place for
defaults).

The two boolean parsers are near copies. Lifting a shared `_flag(prefix, setting, default, env, code)` into one
module is fine if it stays readable. If policy and settings would then have to change together, keep them separate.

### D2. The policy flag `allow_mark_merges_resolved`, true by default

It's added to `Policy` and `read_policy`, with `defaults.ALLOW_MARK_MERGES_RESOLVED = True`. It's read only when the
setting is true. Otherwise a malformed policy value would fail commands that never mark anything, which no more
needs the policy than it needs the setting. `perform` keeps reading its own flag as it does.

The effective decision is one value worked out per command, `Marking`:

```python
@dataclass(frozen=True)
class Marking:
    on: bool
    off_because: Literal["setting", "policy"] | None   # None when on
```

Owner, 2026-10-30: when policy forbids it, act as if the setting were off and say so. The alternative, refusing the
command, would block a merge the person can finish by hand. Policy only forbids the index write, which then doesn't
happen.

### D3. Which paths are marked

A path is marked when all of these hold, worked out from the plan made under the lock:

1. Its action is `write`, `remove` or `finish`, and it isn't `forced`.
2. `merged[path].kind == "conflicted"`.
3. Every side that isn't `None` is vouched for. That's `_merged_from_troupes`'s check of the sides, without its
   clean-merge test.

This covers step 2's rewrite (`keep=True`) and step 1's rewrite of an unmerged path whose sides are both troupe's. A
step-1 path with a side troupe didn't write isn't marked. The person took one side with `git checkout`, and marking
it would resolve the other side away without their asking. So isn't a `--force` replacement (the "never marked"
requirement).

Every command that rewrites such a path marks it: `troupe flush`, the `config set` that writes it, and `sync_files`
when it rewrites a step-1 path. The setting is the person's say-so for the index step, and it applies wherever troupe
already rewrites. D7 of #141 still decides where a rewrite may happen at all.

For a `finish` (D5 of #141), the path is the staged file's target, and the bytes are the staged data.

### D4. The port: `mark_resolved`

```python
@dataclass(frozen=True)
class MergeSides:
    kind: Literal["conflicted", "clean"]
    sides: tuple[bytes | None, ...]
    merged: bytes | None = None
    index: str | None = None
    """Conflicted only: the adapter's own record of the unmerged entries it read, opaque to core and
    given back to mark_resolved. None from an adapter with no index."""

@dataclass(frozen=True)
class Resolve:
    sides: MergeSides       # as merge_sides_under gave it
    data: bytes | None      # the bytes troupe wrote; None: it removed the file

Unmarked = Literal["no-index", "index-changed", "failed"]

def mark_resolved(self, paths: Mapping[str, Resolve]) -> Mapping[str, Unmarked | None]: ...
```

The result has an entry for each path given: `None` when marked, otherwise why not. It returns rather than raises on
`failed`, so files already written and kept aren't hidden behind an error (D6). The files adapter returns `no-index`
for every path.

`index` is opaque, and the git adapter's records (`<mode> <object> <stage>` for each unmerged entry, sorted) are never
compared with troupe's hashes. That keeps #141's D2: core has one definition of a file's hash. Giving `MergeSides`
back whole, rather than only `index`, keeps the port's question one shape.

### D5. How the git adapter marks a path

In one call, for all paths:

1. `git ls-files -u -z -- <paths>` from the theatre, as `merge_sides_under` reads it, gives each path's current
   unmerged entries. A path whose record differs from `sides.index`, or that has none, is `index-changed`.
2. For each path to write: `git hash-object -w --path=<path> --stdin` with the given bytes, run from the theatre, gives
   the object `git add` would store. `--path` applies the path's attributes and filters, as `git add` would. For
   config files, `.troupe/.gitattributes` holds `-text`, so the object is the bytes. The working file is never read.
   The mode is stage 2's, or stage 3's when there's no stage 2, so an executable bit isn't lost. There's no `100644`
   fallback: a conflicted path has at least one of the two.
3. One `git update-index --index-info` from the theatre, with each line naming the path **repository-relative**
   (`theatre_prefix() + path`), because `--index-info` reads paths from the top whatever directory it runs in (see
   Context). Removals go in the same input as `0 <null object> 0\t<path>`, which drops every stage. The null object's
   length is the repository's object format (`git rev-parse --show-object-format`), so this works in a SHA-256
   repository too. `--force-remove` would work just as well, but one input keeps it to one index write.
4. A failure of steps 2 or 3 (`vcs.failed`, such as another git holding `index.lock`, or a timeout) gives `failed`
   for every path not yet marked, and the failure's message is kept for the notice. There's one `update-index` call,
   so it's all or nothing for the paths that got that far.

Every call goes through the adapter's bounded `git()`, as every other git call does. A test runs with the theatre
in a subdirectory of its repository and checks that no stray top-level entry appears.

### D6. Where marking runs, and what it reports

`flush()` gains `marking: Marking` and calls `vcs.mark_resolved` inside the lock, right after `execute`, for the
paths D3 picks. It does this only when `marking.on` and there are such paths, so the files adapter and a setting left
off cost nothing. `Flushed` gains `resolved: Mapping[str, Unmarked | Literal["setting", "policy"] | None]`, by
`.troupe/`-relative path, for every path D3 picks: `None` when marked, or the reason when not. `config_set` does the
same after its final `execute`. Its first `execute` (the files before the change) is marked too, with the same
`marking`.

A rehearsal makes no index call. It reports what it would do: the `FileAction` gains `resolve: bool | None`, true when
it would mark the path, false when D3 picks it but marking is off, and absent when D3 doesn't pick it. The client
protocol's `FileAction` schema gains the optional property.

Notices:

- `config.merge-rewritten` gains `resolved: boolean`, and `unresolved`, which is present only when `resolved` is false:
  `"setting" | "policy" | "index-changed" | "failed" | "no-index"`. A `--force` replacement emits no notice, as
  today, and is never marked (D3), so it needs no reason of its own. Its fix:
  - resolved: "Commit the merge: troupe marked the file resolved."
  - `setting`: "git add .troupe/<path> and commit the merge, or set TROUPE_SETTING_MARK_MERGES_RESOLVED=true to have
    troupe mark it resolved."
  - `policy`: "git add .troupe/<path> and commit the merge. Policy forbids troupe marking it resolved
    (TROUPE_POLICY_ALLOW_MARK_MERGES_RESOLVED=false)."
  - `index-changed`, `failed`: "git add .troupe/<path> …", naming what happened, with git's message for `failed`.
  - `no-index`: today's text without the #156 sentence. A conflicted merge can't come from an adapter without an
    index, but the branch makes the mapping total.
  - A clean merge is never marked: `resolved` is false and `unresolved` is absent. It needs no `git add` during a
    merge in progress beyond what the person commits, and none at all after a merge commit. Its fix keeps today's
    text without the #156 sentence.

  `unresolved` is absent for a clean merge because it's a reason the index step didn't happen, and none was due.
- `config.file-rewritten` gains an optional `resolved: true`, present only when it marked a step-1 path. Its fix stays
  "Nothing to do". A step-1 unmerged path that wasn't marked keeps today's notice: the rule above (D3) doesn't apply
  to it, and saying more about it is outside #156.

### D7. When the settings are read

`read_settings(session.env)` runs at the start of `flush_files`, `config_set` and `sync_files`, so a malformed
`TROUPE_SETTING_*` fails any command that uses config, before anything is written, even when nothing would be marked.
That's the malformed-input rule: a typo shouldn't look like "off" until the day a merge needs it. Policy is read
only when the setting is on (D2).

## Risks / Trade-offs

- **The check and the write aren't atomic.** git has no compare-and-swap for an index entry. A `git add` made between
  step 1's `ls-files` and step 3's `update-index` (milliseconds, both under troupe's config lock) would be
  overwritten with the bytes troupe wrote. → Those bytes are on disk and are what the merged config says, the person's
  previous bytes are in the artifact store, and the window is small. This is the same window as running `git add`
  yourself while an editor saves.
- **Staging applies the path's filters to troupe's bytes.** → That's what `git add` does, and is what the issue
  asks for. Config files are `-text`, so there's no conversion.
- **A partly marked set.** One `update-index` call either marks every path that reached it or none of them. Paths
  that fail the check are left alone and named. → The notices name each path's outcome.
- **`sync_files` can now change the index** (D3: a step-1 rewrite in `perform`). → Only with the setting on, only for a
  path whose sides are both troupe's, and only when troupe rewrote that path in the same command. The notice says so.

## Migration Plan

None. The setting is off by default, the new policy flag is permissive by default, and no event or file changes
format. The notice details are additive. Rollback is reverting the change.
