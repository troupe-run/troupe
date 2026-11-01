## ADDED Requirements

### Requirement: Every package versions on its own
Every workspace member and the protocol SHALL release only when a releasable commit changes files under its own
directory, at its own version, with its own `<component>-v<version>` tag. No two of them SHALL be linked. One release
pull request SHALL gather every component with releasable commits.

#### Scenario: Only one adapter changed
- **WHEN** the only releasable commit since the last release is a `fix:` that changes `packages/troupe-vcs-git/`
- **THEN** the release pull request releases `troupe-vcs-git` alone, at its next patch version
- **AND** no other package's version changes

#### Scenario: Two packages changed
- **WHEN** a `feat:` changes `packages/troupe/` and a `fix:` changes `plugins/runner-scripted/`
- **THEN** one release pull request releases `troupe` at its next minor version and `troupe-runner-scripted` at its
  next patch version

### Requirement: The bundle pins each component at a release tag
Each workspace member in `troupe-run`'s dependencies SHALL be named either bare or as a pin: a direct reference to
this repository at `<component>-v<version>`, with the component's own directory as the subdirectory. A pin's version
SHALL NOT be above the component's manifest version. The repository's check SHALL fail on a pin that breaks this,
naming the dependency, the file and the expected form.

#### Scenario: A pin to another subdirectory
- **WHEN** the bundle pins `troupe-vcs-git` at `troupe-vcs-git-v0.1.0` with `#subdirectory=packages/troupe-vcs-files`
- **THEN** `scripts/check.py` fails, naming `troupe-vcs-git`, `packages/troupe-run/pyproject.toml` and the expected
  reference

#### Scenario: A pin ahead of the release
- **WHEN** the manifest gives `packages/troupe-vcs-git` 0.1.0 and the bundle pins `troupe-vcs-git-v0.2.0`
- **THEN** `scripts/check.py` fails, naming the pin, the manifest's 0.1.0 and the file

#### Scenario: Local development uses the workspace
- **WHEN** the bundle pins every component at a tag and a developer runs `uv sync` in the checkout
- **THEN** every workspace member is installed from the checkout, and `uv sync --locked` succeeds

### Requirement: A component release is followed by a pinning pull request
After release-please publishes releases, the release workflow SHALL open, or update, one pull request that moves each
of the bundle's dependencies that's behind its component's latest release to that release's tag. It SHALL commit as
the release App, with a DCO sign-off. When no dependency is behind, it SHALL open nothing.

#### Scenario: The git port released
- **WHEN** a release pull request that releases `troupe-vcs-git` at 0.1.1 is merged
- **THEN** a pull request opens that changes only the bundle's `troupe-vcs-git` pin to `troupe-vcs-git-v0.1.1`

#### Scenario: Only the bundle or the protocol released
- **WHEN** a release pull request that releases only `troupe-run` and `protocol` is merged
- **THEN** no pinning pull request opens

#### Scenario: A pinning pull request already open
- **WHEN** a pinning pull request is open and another release pull request releases `troupe-stage-local`
- **THEN** the open pinning pull request is updated to pin `troupe-stage-local` as well, and no second one opens

### Requirement: The pinning commit's type is the largest change it pins
The pinning commit SHALL be breaking when any changelog section it now pins, above the version previously pinned, has
breaking changes. Otherwise it SHALL be `feat` when any has features, and otherwise `fix`. Merging it SHALL make the
next release pull request release `troupe-run`.

#### Scenario: A fix in one adapter, a feature in another
- **WHEN** the pins move to a `troupe-vcs-git` release with only fixes and a `troupe-store-text` release with a feature
- **THEN** the pinning commit is a `feat`, and the next release pull request gives `troupe-run` its next minor version

#### Scenario: A breaking change in core
- **WHEN** a pin moves past a `troupe` release whose changelog has breaking changes
- **THEN** the pinning commit is marked breaking, and its footer names `troupe` and the version

### Requirement: The bundle's first release follows its components'
Until `troupe-run` first releases, its release configuration SHALL keep its commits out of release pull requests, so
the components' first release doesn't release it. The first pinning pull request SHALL remove that exclusion, so
merging it releases `troupe-run` at 0.1.0. The check SHALL fail when the exclusion remains after the bundle releases.

#### Scenario: The first release pull request
- **WHEN** release-please regenerates the first release pull request
- **THEN** it releases every component and the protocol at 0.1.0, and doesn't release `troupe-run`

#### Scenario: The first pinning pull request
- **WHEN** the first pinning pull request is merged
- **THEN** the next release pull request releases `troupe-run` at 0.1.0, with each component pinned at `-v0.1.0`

#### Scenario: The exclusion left behind
- **WHEN** the manifest gives `packages/troupe-run` 0.1.0 and its release configuration still excludes its commits
- **THEN** `scripts/check.py` fails, naming the entry and the exclusion to remove

### Requirement: Every workspace member is configured to release on its own
Every workspace member SHALL appear in the release configuration and the version manifest, and the configuration
SHALL link no components. A missing member or a linked group SHALL fail the repository's check, naming the member or
group and the file to fix. For an entry missing from the version manifest, member or protocol, the fix SHALL be the
version of its latest `<component>-v*` tag, or `0.0.0` only if it has none, never a guess.

#### Scenario: A new package without release config
- **WHEN** a package is added under `packages/` but not to the release configuration
- **THEN** `scripts/check.py` fails, naming the package and the configuration file

#### Scenario: A linked group put back
- **WHEN** `release-please-config.json` has a `linked-versions` plugin
- **THEN** `scripts/check.py` fails, naming the plugin's group, the configuration file and that every package versions
  on its own

#### Scenario: A released member lost from the manifest
- **WHEN** `plugins/runner-scripted` has released and its entry is removed from `.release-please-manifest.json`
- **THEN** `scripts/check.py` fails, naming the member, the manifest file and its tags, `troupe-runner-scripted-v*`
- **AND** the message doesn't suggest `0.0.0` as the fix, only as the version when no such tag exists

#### Scenario: The protocol lost from the manifest
- **WHEN** the protocol's entry is removed from `.release-please-manifest.json`
- **THEN** `scripts/check.py` fails, naming the protocol, the manifest file and its tags, `protocol-v*`
- **AND** the message doesn't suggest `0.0.0` as the fix, only as the version when no such tag exists

## MODIFIED Requirements

### Requirement: The protocol has its own version
The protocol SHALL be released on its own: only when a releasable commit changes files under `protocol/`, at its own
version, under the same pre-1.0 rules as every package, tagged `protocol-v<version>`, with its own changelog.

#### Scenario: Only core changed
- **WHEN** the only releasable commits since the last release change `packages/troupe/src/troupe/cli/`
- **THEN** the release pull request doesn't change the protocol's version

#### Scenario: A schema changed
- **WHEN** a `feat` commit changes a schema in `protocol/schemas/` and the troupe package's copy of it
- **THEN** the release pull request releases the protocol and `troupe`, each at its own next version

#### Scenario: Protocol release tag
- **WHEN** a release pull request that releases the protocol at 0.2.0 is merged
- **THEN** the tag `protocol-v0.2.0` and a GitHub release for it exist

## REMOVED Requirements

### Requirement: The bundle and everything it ships share one version
**Reason**: #218 (owner, 2026-11-01): every package versions on its own, so a fix to one adapter doesn't release the
others. The bundle still follows every component release, through the pinning pull request.
**Migration**: None for users: nothing has released. Contributors read "What bumps what" in
`contributing/releasing.md`; the check refuses a linked group.

### Requirement: Every workspace member is configured for release
**Reason**: Replaced by "Every workspace member is configured to release on its own": the check no longer expects a
linked group of what the bundle ships, and refuses any linked group instead.
**Migration**: None: the configuration loses its linked group in the same change.
