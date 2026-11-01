# Proposal

## Why

The 0.1.0 release pull request (#89) is wrong in three ways (#222), and its changelogs become release notes nobody
may edit once they're published, so the fix has to land before #89 merges:

- **Commits sit in the changelogs of components they never changed, and move on every push.** release-please reads
  `main` in pages of 10 commits, and gives a rebase-merged pull request's last commit the whole pull request's
  files when that pull request's other commits fall on another page (googleapis/release-please#2140, fixed only
  within a page by #2141). Each push shifts the page boundaries, so the stray entries move.
- **The oldest commits are missing, and that also moves.** release-please reads at most 500 commits back
  (`commit-search-depth`). `main` has 575, so #89 starts at the 83rd commit: troupe's first features, such as
  `74cbf20` (`--version`, flags anywhere), are in no changelog. Each new commit pushes one more out.
- **`docs` commits are listed, and release.** The `python` release type's default changelog sections show
  `docs` (and `deps`) under **Documentation**, and a visible section makes its commits releasable, so a `docs`
  commit under a package releases it. `contributing/releasing.md` says `docs` and the other non-releasing types
  release nothing and don't appear in changelogs.

## What Changes

- **History is read in pages of 100** (`commit-batch-size: 100`, GraphQL's maximum), as decided in #223 (option A).
  A pull request split by a page boundary is still possible, but much rarer, and impossible while fewer than 100
  commits land between releases. #223 records the other options (wrapping release-please, forking the action,
  reporting it upstream) and when to revisit.
- **History is read 1000 commits back** (`commit-search-depth: 1000`), so every commit on `main` reaches 0.1.0's
  changelogs, and later releases have room.
- **Changelogs show what `releasing.md` says.** `changelog-sections` is set at the top level: `feat`, `fix`,
  `perf` and `revert` shown; `docs`, `deps`, `style`, `chore`, `refactor`, `test`, `build` and `ci` hidden, so they
  neither appear nor release, except a breaking change of any of them, which is listed under breaking changes and
  releases. The doc stays as it is; the config now matches it.
- **The check keeps all three set.** `scripts/release_config.py` fails when any of them is missing or different,
  or when a package entry sets `changelog-sections` itself, naming the file and the fix.
- **The docs say how commits reach changelogs.** `contributing/releasing.md` explains the page size and its limit,
  pointing at #223.

Not in this change: the wrapper, the fork or an upstream issue (#223's other options), and any change to how pull
requests merge.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `releases`: commits of non-releasing types neither appear in changelogs nor release a package; release-please
  reads enough history, in pages of 100; the check enforces the three settings.

## Impact

- `release-please-config.json`: three top-level keys, `commit-batch-size`, `commit-search-depth` and
  `changelog-sections`.
- `scripts/release_config.py` and `scripts/tests/workspace/test_release_config.py`: new problems and their tests.
- `contributing/releasing.md`; `docs/backstage/changelog.md` names the sections a reader will see.
- #89 is rewritten by release-please on the push that merges this: entries move to the components their commits
  changed, the oldest 75 commits join, and **Documentation** sections go. No version changes: every component is
  at 0.1.0 either way.
- No runtime code, and no workflow change: `release.yml` still runs the pinned action.
