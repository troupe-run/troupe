# Design

## Context

See proposal.md for why. The release workflow pins `googleapis/release-please-action` v5.0.0, which depends on
release-please `^17.6.0`; the config's `$schema` names v17.6.0. In that version's source:

- `prerelease` is a releaser option (`schemas/config.json`: "Create the GitHub release as prerelease"). It can be set
  at the top level of the config, and each package takes `pathConfig.prerelease ?? defaultConfig.prerelease`
  (`src/manifest.ts`, `mergeReleaserConfig`), so a top-level value applies to every package that doesn't set its own.
- When it builds the releases to create after a release pull request merges, it sets a release's `prerelease` to
  `config.prerelease && (!!version.preRelease || version.major === 0)` (`src/manifest.ts`, `buildReleases`). So it
  applies only to 0.x versions and semver pre-releases, and stops by itself at 1.0.
- It's not read when building the release pull request, so the pull request (#89) doesn't change.
- It finds earlier releases by walking all of the repository's releases and tags against the manifest, with no
  filter on pre-releases (`src/github.ts` has none), so pre-releases don't hide 0.1.0 from the next release.

Nothing in the repository reads GitHub's "Latest" release (`releases/latest`): the docs name the bundle's tag, and the
install check is given the tag. `release-install-check.yml` triggers on `release: published`, which GitHub fires for
pre-releases too, and filters on the tag name only.

`scripts/release_config.py`'s `problems()` already reads the whole config, and each check returns messages that name
the file and the fix.

## Goals / Non-Goals

**Goals:**
- Every GitHub release below 1.0 is a pre-release, starting with 0.1.0's, set in one place.
- The check refuses a config that would quietly stop doing it.

**Non-Goals:**
- Choosing which release GitHub marks Latest after 1.0 (release-please's default, `make_latest` left unset, still
  applies then).
- Semver pre-release versions (`1.1.0-beta.1`): nothing produces them, and the option would mark them too.

## Decisions

### D1. Set `prerelease` once, at the top level

`"prerelease": true` goes at the top of `release-please-config.json`, next to `bump-minor-pre-major`, so all 11
components inherit it, the protocol included: its 0.x versions carry no stability promise either, and the issue asks
for every release before 1.0.

- *Alternative: on each package entry.* Eleven copies of one decision, and a new package could be added without it.

### D2. Leave it set at 1.0; the docs say it stops by itself

Because release-please applies it only to 0.x versions (Context), it needs no change at 1.0, and each component
leaves pre-release when its own major reaches 1 (the protocol can do so separately from the group).
`contributing/releasing.md` says this, rather than asking whoever releases 1.0 to turn it off.

- *Alternative: say to remove it at 1.0.* An extra step that changes nothing, and that the check (D3) would refuse.

### D3. The check refuses a missing, non-`true` or per-package value

`problems()` gains one more check, in the style of the others:

- Top-level `prerelease` absent: "{CONFIG} doesn't set 'prerelease': set it to true at the top level, so releases
  before 1.0 are pre-releases."
- Present but not the JSON boolean `true` (`false`, `"true"`, `1`): "{CONFIG}'s 'prerelease' is {value}: set it to
  true.", with the value as JSON, the way it's written in the file. A malformed value is an error, not taken as
  absent.
- A package entry (member or protocol) with a `prerelease` key, whatever its value: "{path}'s entry in {CONFIG} sets
  'prerelease': remove it, so it takes the top-level setting." Keeping the decision in one place matters more than
  allowing a redundant `true`.

The copy-of-the-real-files tests then prove the real config has it, and a test per message proves the check names
it.

- *Alternative: only a test that the real config has it.* It would catch the key being removed, but not say why or
  how to fix it, and it wouldn't catch a package overriding it.

### D4. Say it in the contributor and user docs

`contributing/releasing.md`, "How a release happens", step 3: each release is a pre-release while its version is
below 1.0, stopping by itself at 1.0, so GitHub shows no Latest release until then. "Checking each release's
install": a pre-release starts the check too. `docs/backstage/changelog.md` gains one sentence, because that page is
where a user reading a 0.x release on GitHub would look: releases before 1.0 show as Pre-release on GitHub.

## Risks / Trade-offs

- [release-please's behaviour changes in a later 17.x] → The action is pinned by commit, and the config names the
  v17.6.0 schema; a bump that changed `prerelease` would show in the first release after it. The behaviour is also
  checked for real after 0.1.0 (tasks, follow-up).
- [The setting can't be tested locally end to end: a dry run needs the owner's token] → The check proves the config;
  the 0.1.0 releases on GitHub prove the effect, and the follow-up records them on #217.

## Migration Plan

Merge before #89. release-please then rewrites #89 on the push to `main`; its diff should be unchanged, which the
follow-up compares with a copy saved before. If 0.1.0's releases come out as full releases anyway, they can be
edited to pre-release by hand on GitHub (tags don't move), and a fix follows.
