# Spec Delta

## ADDED Requirements

### Requirement: Only releasing commits appear in changelogs
A changelog SHALL list `feat`, `fix`, `perf` and `revert` commits, and breaking changes of any type. Commits of
other types SHALL NOT appear in any changelog and SHALL NOT release a component on their own. A breaking change of
any type SHALL be listed under breaking changes and release its component.

#### Scenario: A docs commit under a package
- **WHEN** the only commit since the last release is a `docs` commit that changes `packages/troupe/README.md`
- **THEN** no release pull request releases `troupe`, and no changelog lists the commit

#### Scenario: A docs commit beside a feature
- **WHEN** a `feat` commit and a `docs` commit both change `packages/troupe/` since the last release
- **THEN** troupe's changelog lists the `feat` commit and has no Documentation section

#### Scenario: A breaking change of a hidden type
- **WHEN** a `refactor!` commit changes `packages/troupe-store-text/`
- **THEN** the release pull request lists it under breaking changes in troupe-store-text's changelog and releases
  the linked group

#### Scenario: A performance fix
- **WHEN** a `perf` commit changes `packages/troupe-vcs-git/`
- **THEN** troupe-vcs-git's changelog lists it under Performance Improvements

### Requirement: The release pull request reads the history since the last release
release-please SHALL read `main` back to the last release, up to 1000 commits, in pages of 100 commits, so a first
release lists every commit on `main` that's shown in a changelog. Pages of 100 are a mitigation, recorded in #223: a
rebase-merged pull request whose commits fall on two pages can still put its last commit under every component the
pull request changed.

#### Scenario: The first release reaches the oldest commits
- **WHEN** the release pull request for 0.1.0 is built from a `main` of fewer than 1000 commits
- **THEN** troupe's changelog lists `74cbf20` (`feat(cli): add --version, flags anywhere, the -- rule and
  structured errors`)

#### Scenario: A rebase-merged pull request within one page
- **WHEN** a pull request with a `feat` commit changing `plugins/runner-scripted/` and a `docs` commit changing only
  `openspec/` is merged by rebase, and both commits are in one page of history
- **THEN** only runner-scripted's changelog lists the `feat` commit, and no changelog lists the `docs` commit

### Requirement: The history and changelog settings are checked
The release configuration SHALL set, at its top level, the page size (100), the search depth (1000) and the
changelog sections. The repository's check SHALL fail when any of them is missing or has another value, or when a
component's entry sets its own changelog sections, naming the configuration file, the setting and the fix.

#### Scenario: The page size removed
- **WHEN** the release configuration doesn't set `commit-batch-size`
- **THEN** `scripts/check.py` fails, naming the configuration file, `commit-batch-size` and that it must be 100

#### Scenario: A smaller search depth
- **WHEN** the release configuration sets `commit-search-depth` to 500
- **THEN** `scripts/check.py` fails, naming the configuration file, the value 500 and that it must be 1000

#### Scenario: Documentation shown again
- **WHEN** the release configuration's `changelog-sections` shows `docs`
- **THEN** `scripts/check.py` fails, naming the configuration file, `changelog-sections` and the sections it must
  be

#### Scenario: A component with its own sections
- **WHEN** the protocol's entry in the release configuration sets `changelog-sections`
- **THEN** `scripts/check.py` fails, naming the protocol, the configuration file and the fix, to remove it from the
  entry
