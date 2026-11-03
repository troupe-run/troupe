# Spec Delta

## RENAMED Requirements

- FROM: `### Requirement: The bundle's first release follows its components'`
- TO: `### Requirement: The bundle doesn't release while it names a member bare`

## MODIFIED Requirements

### Requirement: The bundle doesn't release while it names a member bare
While `troupe-run` names any workspace member bare, its release configuration SHALL keep its commits out of release
pull requests, so no release pull request releases it. Otherwise it SHALL NOT. The check SHALL fail on either mismatch,
naming each bare member, the file and the fix. The pinning pull request SHALL remove the exclusion only when it pins
the last bare member.

#### Scenario: The first release pull request
- **WHEN** release-please regenerates the first release pull request
- **THEN** it releases every component and the protocol at 0.1.0, and doesn't release `troupe-run`

#### Scenario: The first pinning pull request
- **WHEN** the first pinning pull request is merged
- **THEN** the next release pull request releases `troupe-run` at 0.1.0, with each component pinned at `-v0.1.0`

#### Scenario: A new member added after the bundle's first release
- **WHEN** the manifest gives `packages/troupe-run` 0.1.0, a new member `troupe-example` is added to the workspace and
  named bare in the bundle's dependencies, and the bundle's release configuration doesn't exclude its commits
- **THEN** `scripts/check.py` fails, naming `troupe-example`, `release-please-config.json`, the exclusion to add and
  that it stays until `troupe-example` has released and the pinning pull request pins it

#### Scenario: The exclusion added with the new member
- **WHEN** the same new member is named bare and the bundle's release configuration excludes its commits
- **THEN** the check passes, and a releasing commit that touches `packages/troupe-run/` doesn't make the release pull
  request release `troupe-run`

#### Scenario: The exclusion left behind
- **WHEN** the bundle pins every workspace member and its release configuration still excludes its commits
- **THEN** `scripts/check.py` fails, naming the entry and the exclusion to remove

#### Scenario: An exclusion of anything else
- **WHEN** the bundle names a member bare and its release configuration excludes a path other than its own directory
- **THEN** `scripts/check.py` fails, naming the paths and the one exclusion to set

### Requirement: The pinning commit's type is the largest change it pins
The pinning commit SHALL be breaking when any changelog section it now pins, above the version previously pinned, has
breaking changes. Otherwise it SHALL be `feat` when any has features, and otherwise `fix`. When it leaves no member
bare, merging it SHALL make the next release pull request release `troupe-run`, counting every pinning commit since
the bundle's last release.

#### Scenario: A fix in one adapter, a feature in another
- **WHEN** the pins move to a `troupe-vcs-git` release with only fixes and a `troupe-store-text` release with a feature
- **THEN** the pinning commit is a `feat`, and the next release pull request gives `troupe-run` its next minor version

#### Scenario: A breaking change in core
- **WHEN** a pin moves past a `troupe` release whose changelog has breaking changes
- **THEN** the pinning commit is marked breaking, and its footer names `troupe` and the version

#### Scenario: A feature pinned while a member is bare, then the last member pinned
- **WHEN** a pinning commit with a feature is merged while `troupe-plugin-sdk` is still bare, and a later pinning commit
  with only fixes pins `troupe-plugin-sdk`
- **THEN** the first doesn't release `troupe-run`, and after the second the next release pull request gives
  `troupe-run` its next minor version

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

#### Scenario: A pin that leaves a member bare
- **WHEN** a release pull request that releases `troupe` at 0.2.0 is merged while `troupe-plugin-sdk` hasn't released
- **THEN** the pinning pull request moves `troupe`'s pin, keeps the bundle's release exclusion, and its commit message
  says the bundle doesn't release until `troupe-plugin-sdk` is pinned
