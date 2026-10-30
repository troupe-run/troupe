# Tasks

## 1. Pin what must not change (before any code)

- [x] 1.1 On this branch, before any code change, check that the behaviours the design keeps with the setting unset
  have tests that pass on main. They are: `troupe flush` rewriting a conflicted file and leaving it unmerged in git
  (`test_cli_config_merges.py`), the index untouched after a `config set` that resolves a conflicted file, a clean
  merge's index entry unchanged, and `--force` past a hand-edited side. Add any that's missing, plus one test that
  asserts `git ls-files -s` is byte-identical before and after `troupe flush` with no merge in progress. Verify by
  running them on the unchanged code and showing they pass.

## 2. The settings seam and the policy flag (design D1, D2, D7)

- [x] 2.1 Add `core/settings.py` (`TROUPE_SETTING_`, `SettingFlag`, `Settings`, `read_settings`, and
  `settings.invalid-value`) and `defaults.MARK_MERGES_RESOLVED = False`, under a "Settings" heading. Register the
  error code wherever error codes are listed. Verify with `packages/troupe/tests/test_settings.py`, one test per
  `settings` scenario: the default with source `default`, `true` from env with source `env`, empty counting as
  unset, and `yes` failing and naming the variable, the value, `true` and `false`. Add a test that walks every
  request schema and finds no field that sets a setting.
- [x] 2.2 Add `allow_mark_merges_resolved` to `Policy` and `read_policy`, with `defaults.ALLOW_MARK_MERGES_RESOLVED =
  True`, and a function that works out `Marking` from `Settings` and the env, reading policy only when the setting is
  on (D2). Verify in `test_policy.py` and `test_settings.py` that:
  - setting off gives `off_because="setting"`, and a malformed policy value is then not read;
  - setting on and policy unset gives `on`;
  - setting on and policy `false` gives `off_because="policy"`;
  - setting on and policy `nope` fails with `policy.invalid-value`.
- [x] 2.3 Document the seam and the setting: a settings table beside the policy table in
  `docs/the-company/performances-and-runs.md`, the new policy row in both that table and `contributing/runs.md`, and
  the settings seam in `contributing/` next to where policy's seam is described. Verify with the docs tests.

## 3. The VCS port's `mark_resolved` (design D4, D5)

- [x] 3.1 Add `MergeSides.index`, `Resolve`, `Unmarked` and `Vcs.mark_resolved` to `core/vcs.py`, documented as D4
  says. Make the plain filesystem adapter return `no-index` for every path. Verify with mypy --strict, and with a test
  in `packages/troupe-vcs-files/tests/test_files_adapter.py` that it marks nothing and reports `no-index`.
- [x] 3.2 Make the git adapter's conflicted reading (`merges.py`, `_conflicted`) fill `index` with its sorted
  `<mode> <object> <stage>` records. Verify in `test_git_merge_sides.py` that two reads of the same unmerged path
  give equal `index`, and that `git add` on the path between reads changes it.
- [x] 3.3 Implement the git adapter's `mark_resolved` as D5 says: re-read with `ls-files -u`, `hash-object -w --path`
  from the given bytes, the mode from stage 2 or else 3, and one `update-index --index-info` with repository-relative
  paths and the object format's null object for removals. Map a `vcs.failed` to `failed` with its message. Verify
  with real repositories in `packages/troupe-vcs-git/tests/test_git_mark_resolved.py`, one test per `vcs` scenario:
  - a three-stage conflict ends with one stage-0 entry whose blob is the given bytes, and `git commit --no-edit`
    succeeds;
  - a modify/delete removal leaves no entry;
  - with the working file holding other bytes, the index holds the given bytes;
  - `git add` after the read gives `index-changed` and leaves the entry alone;
  - an aborted merge gives `index-changed`;
  - a theatre in a subdirectory of its repository marks `sub/...`, and `git ls-files -s` lists no stray top-level
    path. This pins the Context finding;
  - an executable stage-2 mode is kept;
  - a SHA-256 repository removes correctly;
  - another process holding `index.lock` gives `failed`, and the index is unchanged.

  Each test's name states only what its body checks.

## 4. Marking from the projection and commands (design D3, D6)

- [x] 4.1 In `projection.py`, pick the paths to mark (D3) from the final plan, give `flush()` a `marking`, call
  `vcs.mark_resolved` under the lock after `execute` when `marking.on` and there's something to mark, and carry
  `resolved` on `Flushed`. Verify with unit tests in `test_config_files.py` using a fake `Vcs` that records its calls:
  - D3 picks a step-2 conflicted rewrite, a step-1 unmerged rewrite with both sides vouched, and a `finish` over a
    recognised file, with the staged bytes;
  - D3 never picks a clean merge, a `--force` replacement, a step-1 path with a side not vouched, or an unmerged path
    already matching config;
  - with `marking` off, the fake is never called;
  - a rehearsal never calls it, and reports `resolve` true or false per path.
- [x] 4.2 Update `merge_notices` and `Flushed.notices()` with the `resolved` and `unresolved` details and D6's fix for
  each case, and add the optional `resolved` to `config.file-rewritten`. Update `notice.schema.json` (both notices)
  and the `FileAction` schema (`resolve`). Remove the `#156` sentence. Verify with schema tests that a notice of each
  case validates and an unknown `unresolved` value doesn't, and with unit tests of each fix's text.
- [x] 4.3 Wire `read_settings` and `Marking` into `flush_files`, `config_set` (both `execute`s) and `sync_files` (D7).
  Verify with CLI tests in `test_cli_config_merges.py` that drive real git merges, one per `config-files` scenario:
  - marked resolved by `troupe flush`, after which `git commit --no-edit` succeeds with no `git add`;
  - removed and marked by the `config set` that resolves config;
  - only the rewritten path is staged: a cleanly merged config file, an unmerged source file and the event segments
    keep their index entries;
  - unmerged but already matching config: nothing written and still unmerged;
  - a rehearsal leaves the index unchanged and says it would mark;
  - forbidden by policy: rewritten, still unmerged, with the notice naming the policy variable;
  - `--force` past a hand-edited side: still unmerged;
  - a malformed `TROUPE_SETTING_MARK_MERGES_RESOLVED` fails `troupe flush` with `settings.invalid-value`, and nothing
    is written and the index is unchanged;
  - with the setting unset, the notice says to `git add` and names the setting.
- [x] 4.4 Extend the property test in `test_config_merge_files.py` (small example budget, as now) with the setting
  on. After the merge and one troupe command, check that every config path troupe rewrote is no longer unmerged, its
  index blob equals what config writes, and no other path's index entry changed. Verify that it passes under the CI
  hypothesis profile.
- [x] 4.5 Update `docs/stagecraft/hand-edit-config.md` (Branches): with the setting on, troupe marks the file
  resolved and the person only commits. Name the setting, its default, and the policy that can forbid it, and say
  what's never marked (a clean merge, a forced file, a side troupe didn't write). Update the table and notice list in
  `contributing/config.md`. Verify with the docs tests, and by running the documented commands in a scratch
  repository.

## 5. Integration

- [ ] 5.1 Raise a troupe-run/infrastructure issue, on the roadmap board, to record the new `settings` spec's Purpose in
  `oob/troupe-spec-purposes.json`. Check `cap:settings`'s description against that Purpose. Verify with `gh issue view
  <n> -R troupe-run/infrastructure --json projectItems`.
- [ ] 5.2 Run `uv run scripts/check.py` and show it passes. Then push, and verify that every CI job passes on Linux,
  macOS and Windows.

## Workflow follow-up

- Open the PR with `Closes #156`, linking the infrastructure issue from 5.1.
- Act on Claude's review of the last push, then run `/opsx:archive` on the branch before merging.
- After the merge, comment on #156 with the PR and the archived change. Check it's closed and its card says Done.
