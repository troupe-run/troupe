# Design

## Context

See proposal.md for why. The release workflow pins `googleapis/release-please-action` v5.0.0, which bundles
release-please 17.6.0; the config's `$schema` names v17.6.0. In that version's source:

- **Paging** (`src/github.ts`, `mergeCommitsGraphQL`). History is read `commit-batch-size` commits at a time
  (default 10, GraphQL's maximum 100). A commit takes its pull request's file list (first 100 files) when it's the
  pull request's `mergeCommit` and the only commit of that pull request in the current page; otherwise it gets its
  own files over REST. Under rebase merges a pull request's last commit is its `mergeCommit`, so a pull request
  split across a page boundary gives its last commit every file it changed. Unchanged in 17.11.2, the latest.
- **Depth** (`src/manifest.ts`). `commit-search-depth` (default 500) caps how many commits are read, back to the last
  release. Both settings are top-level only: the schema doesn't allow them in a package entry.
- **Sections** (`src/strategies/python.ts`). With no `changelog-sections`, the `python` strategy shows `docs` and
  `deps`; the `simple` strategy (the protocol) uses the preset's defaults, which hide `docs`. A release is skipped
  only when its changelog section would be empty (`strategies/base.ts`, `changelogEmpty`), so a shown type
  releases. A hidden type's breaking change is still written under breaking changes
  (`conventional-changelog-conventionalcommits` 6, `writer-opts.js`), so it still releases.
  `changelog-sections` is a releaser option: top-level, inherited by each package unless the package sets its own.

**The settings were tried before they were chosen** (2026-11-01, #223). `main`'s 575 commits were fetched with
release-please's own GraphQL query at 100 a page (each page took 4 to 6 s, so a page that size isn't refused), and
its paging rule was replayed offline for every page offset. At 10 a page the replay reproduces both #89 builds that
#222 compares, `5adefde` and `cd20f75`, entry for entry. At 100 a page, with the depth and sections below, 2 of the
100 offsets put a shown commit under a component it didn't change: `dd6189b` (`fix(runs)`, under protocol and
vcs-git) once 18 commits have landed on today's `main`, and `69d6c27` (`feat(runners)!`, under three adapters) once
68 have. Today's `main` has none. The replay scripts are throwaway; #223 records the result.

`scripts/release_config.py`'s `problems()` reads the whole config; each check returns messages naming the file and
the fix, and `_prerelease_problems` (prerelease-before-1-0 D3) is the pattern for a setting held at the top level.

## Goals / Non-Goals

**Goals:**
- #89's changelogs list each shown commit under the components it changed, every commit on `main` included.
- The config can't quietly lose any of the three settings.

**Non-Goals:**
- Making the page-boundary case impossible: that's #223's options B to D, deferred.
- Changing the section titles release-please already writes (Features, Bug Fixes, and so on).

## Decisions

### D1. Pages of 100

`"commit-batch-size": 100` at the top level, the largest page GraphQL allows, as #223 decided. The larger the page,
the fewer boundaries a pull request can straddle, and once the history since the last release fits on one page
there are none. Each page asks for up to 100 commits × 10 pull requests × 100 files; GitHub served all six pages of
`main` (see Context).

- *Alternative: a smaller page, say 50, to stay further from GraphQL's limits.* Twice the boundaries, and 100 was
  served comfortably.

### D2. Search 1000 commits

`"commit-search-depth": 1000` at the top level (owner, 2026-11-01). It covers `main`'s 575 commits with room for
the ones that land before #89 merges, and after 0.1.0 it bounds only the commits between two releases. Hitting it
would silently drop the oldest commits again, and #223's "more than 100 commits between releases" trigger comes long
before it.

- *Alternative: a much larger depth.* No gain now, and a first release isn't coming again.

### D3. Changelog sections, set once

`changelog-sections` at the top level, in this order, with release-please's own titles so #89's headings don't
change:

| type | section | hidden |
|---|---|---|
| `feat` | Features | |
| `fix` | Bug Fixes | |
| `perf` | Performance Improvements | |
| `revert` | Reverts | |
| `docs` | Documentation | yes |
| `deps` | Dependencies | yes |
| `style` | Styles | yes |
| `chore` | Miscellaneous Chores | yes |
| `refactor` | Code Refactoring | yes |
| `test` | Tests | yes |
| `build` | Build System | yes |
| `ci` | Continuous Integration | yes |

The hidden types are listed, not left out, so the list says what happens to each type the guard accepts. This
matches `releasing.md` rather than changing it: its "What bumps what" table and "release nothing on their own" are
already the intended behaviour (#222's done-when allows either).

- *Alternative: change the doc to match the defaults.* A `docs` commit under a package would release it, which the
  versioning table doesn't allow for, and the protocol (the `simple` strategy) would still behave differently.

### D4. The check holds the three values

`release_config.py` names `COMMIT_BATCH_SIZE = 100`, `COMMIT_SEARCH_DEPTH = 1000` and `CHANGELOG_SECTIONS` (D3's
table), each with a docstring citing this design and #223, and `problems()` gains `_history_problems`:

- A setting missing: "{CONFIG} doesn't set '{key}': set it to {value} at the top level ({why})."
- A setting with another value: "{CONFIG}'s '{key}' is {json value}: set it to {value}." For the sections, the
  message gives the expected list as JSON. A wrong type (`"100"`) is another value, not absent.
- A package entry with `changelog-sections`: "{path}'s entry in {CONFIG} sets 'changelog-sections': remove it, so
  it takes the top-level setting." Package entries can't hold the other two (the schema refuses them), so the check
  doesn't look for them there.

The copy-of-the-real-files tests then prove the real config has them.

- *Alternative: check only that each is present.* Shrinking the page or depth, or showing `docs` again, would pass.

### D5. Docs

`contributing/releasing.md`, "What bumps what": say the config's `changelog-sections` is what keeps the other types
out of changelogs and releases, and that their breaking changes are still listed. A new short section, "How commits
reach changelogs", explains the page size, its limit and its revisit triggers, pointing at #223, and the depth.
`docs/backstage/changelog.md` names the sections a reader sees (Features, Bug Fixes, Performance Improvements,
Reverts, and breaking changes first).

## Risks / Trade-offs

- [A pull request straddles a page boundary before #89 merges] → The replay shows the offsets where it happens
  (+18, +68 commits). This change adds a few commits; after the merge, #89's regenerated diff is checked entry by
  entry (tasks, follow-up). If a stray appears, that's #223's revisit trigger, before #89 merges.
- [GitHub refuses or times out on 100-commit pages later] → release-please retries and then fails the run, which is
  visible (googleapis/release-please#2592 reports 502s). Lowering the page size is a one-line change, with the check
  updated alongside.
- [It can't be tested end to end here: a dry run needs the owner's token] → The check proves the config, the
  schema validation proves release-please accepts it, and the owner can dry-run the branch (tasks 3.2). The
  regenerated #89 is the final proof.

## Migration Plan

Merge before #89. The push that merges it makes release-please rewrite #89: entries move to the right components,
the oldest commits appear, and Documentation sections go; versions stay at 0.1.0. Rolling back is reverting the
config keys; nothing else depends on them.
