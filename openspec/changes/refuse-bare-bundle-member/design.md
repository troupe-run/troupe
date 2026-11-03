# Design: the bundle doesn't release while it names a member bare

See [proposal.md](proposal.md) for why, and the [releases delta](specs/releases/spec.md) for the behaviour.

## Context

- **release-please releases a component from the commits that touch its directory** since its last tag, read with the
  config on `main`. `troupe-run`'s entry can set `"exclude-paths": ["packages/troupe-run"]`, which drops those commits,
  so a release pull request doesn't release it. release-each-package D7 used this once, before the bundle's first
  release. The first pinning commit removed it, and the next release pull request released `troupe-run` at 0.1.0.
- **`scripts/release_config.py`'s `_bootstrap_problems`** allows the exclusion only while the manifest gives the bundle
  0.0.0, and only as exactly its own directory. `_pin_problems` checks each dependency is bare or a well-formed pin at
  or below the member's release.
- **`scripts/pin_bundle.py`** moves each pin that's behind the manifest. Whenever it moves anything, it also removes
  the exclusion line (`_unexcluded`), byte for byte.
- **`main` today:** `troupe-run` is at 0.1.0 with no exclusion, and `troupe-plugin-sdk` is bare at 0.0.0 (runner-sdk
  D12). `scripts/tests/bundle_state.py` builds the "unpinned" state as "every member bare, the exclusion set, the
  bundle at 0.0.0". Its docstring says those three go together.

## Goals / Non-Goals

**Goals:**
- No release pull request can release `troupe-run` while a member is bare, enforced by the check rather than by
  which commit types people choose.
- Nothing deadlocks. A release pull request that has to release the bare member itself is never held up.

**Non-Goals:**
- Refusing a release pull request in CI by comparing its base and head manifests (see D1).
- Changing the install check on published tags. It stays the backstop.
- Checking that a pinned member's own dependencies are pinned. `bundle.py` already does that (installation spec,
  runner-sdk D12).

## Decisions

### D1. Prevent the release, rather than refuse the release pull request

The bundle stays out of release pull requests while it names a member bare (owner, 2026-11-03, choosing between the
options below).

- **Refuse in CI** (the issue's literal reading): a step diffs the release pull request's base and head manifests,
  and fails if `troupe-run`'s version moves while a member is bare. Rejected because it can deadlock. The release
  pull request that fails may be the one that has to release the bare member, for example the SDK's first release
  alongside a `feat` that touched `packages/troupe-run/`. Its only way out is to add the exclusion by hand, which is
  this design anyway. It would also need a base revision, which `scripts/check.py` doesn't have locally.
- **Both:** with the rule in place, the CI refusal can't fire, short of a hand-edited release pull request. It's code
  to keep for a case the check already makes unreachable.

The check still refuses, as the issue asks. It refuses the state that would let a release pull request release a bare
bundle, at the commit that creates it, and names the member and the fix.

### D2. The rule is "excluded exactly while anything is bare", and it reads only the tree

`_bootstrap_problems` becomes `_exclusion_problems(bundle, entry, bare)`, where `bare` is the sorted names of the
workspace members the bundle names bare (`pinned_version(...) is None`). A malformed pin isn't counted as bare,
because `_pin_problems` already reports it. One rule replaces the release-dependent one:

| Bare members | Exclusion | Result |
|---|---|---|
| none | absent | passes |
| none | set | fails: remove it, or `troupe-run`'s commits never release |
| some | `[<bundle>]` | passes |
| some | absent | fails: names each bare member, `release-please-config.json`, the line to add, and that it stays until each has released and the pinning pull request pins it |
| some | anything else | fails: names the paths, and the one exclusion to set (as today) |

It doesn't depend on whether the bundle or the members have released. So "before the first release" is the same rule:
every member is bare, so the exclusion is required. That's what D7 did, so the first-release scenarios still hold. A
new member gets the same treatment at any point in the bundle's life.

The rule lives in `release_config.py`, beside the pin check, because it's about the release configuration. `bundle.py`
stays about what the bundle depends on.

### D3. The pinning step removes the exclusion only when nothing is left bare

`pin_bundle.apply` works out the bare members after its moves, and calls `_unexcluded` only when there are none.
`message` then adds a paragraph when some stay bare: `troupe-run` stays out of release pull requests until it pins
them, naming each one. The commit's type rules don't change. A pinning commit made while a member is bare touches
`packages/troupe-run/`, so release-please reads it again once the exclusion goes, and the bundle's next release is the
size of the largest change pinned since its last tag. The release workflow's pull request description loses its fixed
"Merging it releases troupe-run" line. The message, which the description quotes, says which case it is.

### D4. `main` gets the exclusion in this change

This change adds the exclusion line to `troupe-run`'s entry, on its own line after `"component"`, the one form
`_unexcluded` can remove. Otherwise the new check fails on `main`, since the SDK is bare. The commit touches only
root files, which belong to no component, so it releases nothing.

### D5. Tests build the new-member state, not assume it

Following pin-tests-any-state D1, a test can't assume which state the repository is in. `bundle_state.py` gets
`add_member(root, name)`. In a copy, it creates `packages/<name>/pyproject.toml`, adds the member's release
config entry (with its `uv.lock` extra-file), the manifest at 0.0.0, the `uv.lock` package entry that release_config
checks, and a bare dependency in the bundle. The issue's test is then: from `pinned` with the bundle at 0.1.0,
`add_member` without the exclusion fails naming the member, and with the exclusion it passes. The pinning step keeps
the exclusion while that member is at 0.0.0, and removes it once the manifest gives it a release with a changelog.
`unpinned`'s docstring changes, since the exclusion now goes with "something is bare", not with "the bundle is at
0.0.0".

## Risks / Trade-offs

- [release-please might not count commits from before the exclusion was removed] → D7's first release relied on the
  same reading and released `troupe-run` 0.1.0 as expected. Here a previous `troupe-run` tag exists, but release-please
  walks the commits since that tag with the config at `main` either way, and `commit-search-depth` (1000) covers the
  range. If a release pull request ever doesn't release the bundle after the last pin, a `Release-As` footer releases
  it (contributing/releasing.md).
- [A release pull request opened before a bare member landed, merged before release-please updates it] → it would tag
  a commit that names the member bare. release-please regenerates the pull request on the same push that adds the
  member and the exclusion, so the window is the length of one release workflow run. The install check on published
  tags still opens a Bug if it's ever hit.
- [The bundle's releasable changes wait while a member is unreleased] → by design: they ship with the pin that clears
  the last bare member. Releasing the member is one merge of the release pull request, so the wait is short.

## Migration Plan

Merge with the exclusion on `main`. After the SDK's first release, the pinning pull request pins it and removes the
exclusion, and the release pull request after that releases `troupe-run`. To roll back, revert the change. The
exclusion line then fails the old check (the bundle has released), so the revert removes it too.
