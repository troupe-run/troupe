# Tasks

## 1. Pin what must not change (before any code)

- [x] 1.1 On this branch before any code change, check that the behaviours the design's goals keep have tests that
  pass on main. These are: a hand edit refused (`test_cli_config.py`, `test_config_files.py`), an older version
  rewritten, a clean merge that matches config left alone
  (`test_a_clean_git_merge_of_two_branches_files_is_left_as_it_is`), `--force` keeping a copy, and a staged write
  finished or discarded. Add any that's missing. Add one more test that passes on main: a theatre with no merge in
  progress and a single-parent HEAD, whose hand-edited `tester.yaml` holds conflict markers, is refused with
  today's markers wording. It must stay refused. Verify by running those tests and showing them pass on the
  unchanged code.

## 2. The VCS port's merge sides (design D2, D3)

- [x] 2.1 Add `MergeSides` and `merge_sides_under(directory)` to `core/vcs.py`, documented as D2 says (theatre-relative
  paths, sides as bytes, no base). Make the plain-filesystem adapter return `{}`. Verify that mypy --strict passes,
  and with a test in `packages/troupe-vcs-files/tests/test_files_adapter.py` that it reports none.
- [x] 2.2 Git adapter, conflicted paths: `git ls-files -u -z` under the directory, with stages 2 and 3 read by one
  `git cat-file --batch`, and a stage that isn't listed reported as `None`. Paths are theatre-relative when the
  theatre is a subdirectory of its repository. Verify with real repositories in
  `packages/troupe-vcs-git/tests/test_git_merge_sides.py`:
  - a content conflict gives both sides byte for byte;
  - a modify/delete gives ours `None`;
  - a cherry-pick conflict is reported;
  - a theatre in a subdirectory reports theatre-relative paths;
  - a path outside the directory is left out.
- [x] 2.3 Git adapter, clean merges: from `MERGE_HEAD` with the index's stage-0 blob, or from HEAD's two parents with
  HEAD's blob. Only paths whose merged blob differs from every parent's count. The merge is reproduced with `git
  merge-tree --write-tree` on the two parents (design D3). Verify with
  real repositories in `test_git_merge_sides.py`:
  - a clean merge in progress (stopped by another file's conflict) is reported;
  - a committed clean merge is reported;
  - a merge commit whose file was edited before committing is left out;
  - an octopus merge reports none;
  - a path merge-tree lists as conflicted is left out, even when the merge committed it with its markers;
  - a single-parent HEAD with no `MERGE_HEAD` reports none;
  - a path equal to one parent's version is left out.

  Each test's name states only what its body checks.
- [x] 2.4 Document the query in `contributing/config.md`, next to the table of what counts as troupe's file, and add
  a line in `contributing/event-store.md` where it lists the port's reads. Say why it uses `merge-tree`
  rather than `merge-file`. Verify with the docs tests.

## 3. Recognising a merged file in the projection (design D4, D5)

- [x] 3.1 Give `projection.plan` and `flush` the `merges` and `resolve` inputs, apply D4's order, and add `keep` to
  `Action`. Make `execute` keep a copy for `forced or keep`, including on a `finish` over a recognised file (D5).
  Verify with unit tests in `test_config_files.py`, using `MergeSides` values and no git:
  - a recognised path that isn't in `resolve`: refused with the `MERGED` reason, and nothing written;
  - conflicted, both sides vouched: written and kept, whatever the working file holds (markers, a half-resolved
    file);
  - conflicted, one side `None` and the other vouched: written or removed as config says, and kept;
  - conflicted, a side not vouched: refused, and the refusal names that side;
  - clean, the working file equals `merged`: written and kept;
  - clean, the working file differs from `merged`: refused as a hand edit;
  - a working file already vouched: replaced with no copy, as now;
  - a finished staged write over a recognised file keeps the target's bytes first.
- [x] 3.2 Change `refuse`'s markers message to D4 step 4's (it names the side that isn't troupe's and the
  `--ours`/`--theirs` side to take, or `--force`), and drop the "(#141)" interim text. Add the `MERGED` refusal, which
  says the file is a merge of versions troupe wrote and that `troupe flush` rewrites it, keeping a copy. Verify with
  refusal tests in `test_config_files.py` and `test_cli_config_merges.py`, each named for what it checks.

## 4. The commands and the notice (design D6, D7)

- [x] 4.1 Add `config.merge-rewritten` to `core/notices.py` and to `protocol/schemas/notice.schema.json`, with the
  details `merge`, `action` and `kept`, and the package's bundled copy. List it in `contributing/config.md`. Verify
  with `test_notices.py`, the protocol schema tests and the docs tests.
- [x] 4.2 Pass `store.vcs.merge_sides_under(...)` for the config directories into every plan in `sync_files`,
  `flush_files` and `config_set`, read again for the plan made under the lock. Pass `resolve` as D7 says: every
  merged path for `flush`, the paths its change writes for `config set` (working out its entries before its first
  plan), and none for `sync_files`. Emit the notice from `Flushed.notices()` and from `config set` for kept files.
  Verify with CLI tests in `test_cli_config_merges.py` (and the converted test in `test_cli_config.py`) that
  drive real git merges, one per config-files scenario:
  - config clean but the file conflicted, rewritten by `troupe flush` with both branches' changes, and the file still
    unmerged in git;
  - `troupe perform` refused, naming `troupe flush`, with the file unchanged and no run started;
  - `config set` of an unrelated value refused, naming `troupe flush`, with nothing recorded;
  - a config conflict resolved by `config set`, with the conflicted bytes kept;
  - a half-done hand resolution kept under the named hash;
  - modify/delete;
  - git's clean line merge of two character edits with config conflicting, accepted by `config set`;
  - a clean merge edited afterwards, refused;
  - a merge older than HEAD, refused;
  - `flush --rehearse` naming the file and its reason, and writing and keeping nothing;
  - the plain-filesystem adapter refusing a file with markers.

  Turn today's conflicted-file test into the "A file git left conflicted" scenario: accepted, with no `git
  checkout --ours`. Each test asserts the rewritten file equals `render(merged config)` and differs from both sides.
- [ ] 4.3 Add a property test in `test_config_merge_properties.py` (or a new `test_config_merge_files.py`), with a
  small example budget since it drives real git. For generated changes to one actor on two branches, after
  `git merge` and one troupe command (`flush`, or `config set` when config conflicts), check that:
  - no file is refused;
  - every config file equals `render(merged config)`;
  - every replaced file's bytes are in the artifact store.

  Verify that it passes under the CI hypothesis profile.

## 5. Docs

- [ ] 5.1 Replace the manual steps in `docs/stagecraft/hand-edit-config.md` (Branches) with what happens now: `troupe
  flush` (or the `config set` that resolves a config conflict) rewrites the file from the merged config and keeps a
  copy, other commands refuse it and name `troupe flush`, and the person runs `git add` and commits (#156 will drop
  the `git add`). Say what's still refused (a side troupe didn't write, an edited or older merge) and its fix. Update
  the table in `contributing/config.md`. Verify with the docs tests, and by running the documented commands in a
  scratch repository.

## 6. Integration

- [ ] 6.1 Run `uv run scripts/check.py` and show it passes. Then push, and verify that every CI job passes on Linux,
  macOS and Windows.

## Workflow follow-up

- Open the PR with `Closes #141`, and mention #156 as the follow-on.
- Run `/opsx:archive` on the branch before merging.
- After the merge, comment on #141 with the PR and the archived change. Check it's closed and its card says Done, and
  that #156 stays open.
