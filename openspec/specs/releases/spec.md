# releases Specification

## Purpose

Capability: `cap:development`

How troupe's packages get their versions, changelogs and releases: all derived from the Conventional Commits on
`main` through a release pull request, never edited by hand.

## Requirements

### Requirement: Versions and changelogs come from the commit history
A package's version and changelog SHALL change only through a release pull request, which is opened and updated
automatically from the Conventional Commits on `main` that touch the package. A commit that touches no package
paths SHALL change no version.

#### Scenario: A releasable commit lands
- **WHEN** a `feat` or `fix` commit that changes files under `packages/troupe/` lands on `main`
- **THEN** a release pull request is opened, or updated if one is open, with the bumped version and a changelog
  entry for that commit

#### Scenario: A commit outside every package
- **WHEN** a commit that changes only `openspec/` or `scripts/` lands on `main`
- **THEN** no package's version or changelog changes because of it

### Requirement: Pre-1.0 versioning
While a package's major version is 0, a breaking change SHALL bump its minor version, and a `feat` or `fix` SHALL
bump at most its minor version. The first release of every package SHALL be 0.1.0.

#### Scenario: Breaking change before 1.0
- **WHEN** a package at 0.3.2 has a released commit marked breaking (`!` or a `BREAKING CHANGE:` footer)
- **THEN** its next version is 0.4.0

#### Scenario: First release
- **WHEN** the first release pull request is merged
- **THEN** every package it releases is at version 0.1.0

### Requirement: Every package has its own changelog
Each package SHALL have a `CHANGELOG.md` in its own directory, listing the released commits that touched it, under
the version that released them.

#### Scenario: Changelog location
- **WHEN** a release pull request releases `troupe-runner-scripted`
- **THEN** it updates `plugins/runner-scripted/CHANGELOG.md`

### Requirement: The release pull request keeps the lock file in step
A release pull request SHALL update each released package's version in `uv.lock` together with its
`pyproject.toml`, so the lock file stays consistent with the workspace.

#### Scenario: Lock file after a version bump
- **WHEN** CI runs on a release pull request
- **THEN** `uv sync --locked` succeeds

### Requirement: The release pull request passes every required check
The release pull request SHALL be opened by the release App, whose pull requests trigger CI. Every commit on it
SHALL be authored by the release App's bot account, and SHALL be a Conventional Commit with a DCO sign-off. The
required checks then run and pass, with no exemption apart from the release-branch exemption granted in
`development-workflow`.

#### Scenario: Required checks on the release pull request
- **WHEN** a release pull request is opened or updated
- **THEN** the CI, DCO and guard checks all run on it

#### Scenario: A commit on the release branch by anyone else
- **WHEN** the release branch carries a commit authored by anyone other than the release App's bot account
- **THEN** the guard check fails on the release pull request

### Requirement: Merging the release pull request publishes the release
When a release pull request is merged into `main`, a tag `<package>-v<version>` and a GitHub release SHALL be
created for each package it released, with that version's changelog section as the release notes.

#### Scenario: Release after merge
- **WHEN** a release pull request that releases `troupe` at 0.1.0 is merged
- **THEN** the tag `troupe-v0.1.0` and a GitHub release for it exist

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

### Requirement: A protocol release updates the version troupe records
A release pull request that releases the protocol SHALL set the protocol version the troupe package records to the
new version, in the same pull request. The repository's check SHALL fail when the recorded version differs from the
manifest's protocol version, or when the protocol's release configuration doesn't update it, naming the file and fix.

#### Scenario: The release pull request
- **WHEN** a release pull request bumps the protocol from 0.1.0 to 0.2.0
- **THEN** it also changes the version the troupe package records from 0.1.0 to 0.2.0
- **AND** `scripts/check.py` passes on it

#### Scenario: A recorded version edited by hand
- **WHEN** the version the troupe package records differs from the protocol's version in the manifest
- **THEN** `scripts/check.py` fails, naming both files and both versions

#### Scenario: The update left out of the release configuration
- **WHEN** the protocol's entry in the release configuration doesn't update the recorded version
- **THEN** `scripts/check.py` fails, naming the entry and the update to add

### Requirement: Releases before 1.0 are pre-releases
A GitHub release for a component version whose major is 0 SHALL be created as a pre-release. A release at 1.0 or
later SHALL NOT be, unless its version carries a pre-release suffix. The setting SHALL NOT change the release pull
request, and a pre-release SHALL start the release install check like any other published release.

#### Scenario: The first release
- **WHEN** the release pull request that releases the linked group and the protocol at 0.1.0 is merged
- **THEN** every GitHub release it creates, `troupe-run-v0.1.0` and `protocol-v0.1.0` included, is marked
  Pre-release
- **AND** none of them is marked Latest

#### Scenario: A component reaches 1.0
- **WHEN** a release pull request that releases the linked group at 1.0.0 is merged
- **THEN** its GitHub releases aren't marked Pre-release

#### Scenario: The install check runs for a pre-release
- **WHEN** the `troupe-run-v0.1.0` pre-release is published
- **THEN** the release install check runs against `troupe-run-v0.1.0`

### Requirement: The pre-release setting is checked
The release configuration SHALL set pre-releases once for every component. The repository's check SHALL fail when
it isn't set to true, or when a component's own entry sets it, naming the configuration file and the fix.

#### Scenario: The setting removed
- **WHEN** the release configuration doesn't set `prerelease` at the top level
- **THEN** `scripts/check.py` fails, naming the configuration file and that `prerelease` must be `true`

#### Scenario: The setting not true
- **WHEN** the release configuration's top-level `prerelease` is `false`, or the string `"true"`
- **THEN** `scripts/check.py` fails, naming the configuration file, the value and that it must be `true`

#### Scenario: A component overriding it
- **WHEN** the protocol's entry in the release configuration sets `prerelease`
- **THEN** `scripts/check.py` fails, naming the protocol, the configuration file and the fix, to remove it from the
  entry

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

#### Scenario: A pin that leaves a member bare
- **WHEN** a release pull request that releases `troupe` at 0.2.0 is merged while `troupe-plugin-sdk` hasn't released
- **THEN** the pinning pull request moves `troupe`'s pin, keeps the bundle's release exclusion, and its commit message
  says the bundle doesn't release until `troupe-plugin-sdk` is pinned

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

### Requirement: Dependabot proposes no version for a workspace member
A workspace member's version moves only through its own release, so Dependabot SHALL ignore every workspace member in
troupe's `uv` update entry, whatever a package index holds under its name. Each member's name SHALL be matched by an
ignore in that entry of the delivered `.github/dependabot.yml` that covers every version, and the repository's check
SHALL fail when one isn't.

#### Scenario: Dependabot's scheduled run
- **WHEN** Dependabot's `uv` job runs in troupe and PyPI has a release named `troupe`, or named like another member
- **THEN** the job proposes no update to a workspace member and fails for none

#### Scenario: Every member is covered
- **WHEN** `scripts/check.py` runs on the repository as it is
- **THEN** the check passes, every member's name matched by an ignore in the `uv` entry

#### Scenario: A member named outside the ignores
- **WHEN** a workspace member's name is matched by no ignore in the `uv` entry
- **THEN** `scripts/check.py` fails, naming the member, `.github/dependabot.yml`, and that the ignore is added in
  troupe-run/infrastructure's Dependabot policy

#### Scenario: An ignore that covers only some versions
- **WHEN** the only ignore matching a member's name also limits the versions or update types it ignores
- **THEN** `scripts/check.py` fails for that member, as if nothing matched it

#### Scenario: Names are compared as packaging compares them
- **WHEN** an ignore's name differs from a member's only in case, or in `-`, `_` and `.`
- **THEN** it matches that member, and a `*` in it matches any run of characters

#### Scenario: No uv entry to read
- **WHEN** `.github/dependabot.yml` is missing, can't be parsed, or has no `uv` entry for `/`
- **THEN** `scripts/check.py` fails, naming the file and what it lacks, and doesn't pass for want of anything to check

### Requirement: The bundle's extras follow its dependencies' rules
Every rule for `troupe-run`'s dependencies SHALL hold for each entry in its extras as well: the bare-or-pinned form,
pins no higher than the manifest, the pinning pull request moving pins that are behind, its commit type, and the hold
on releasing while a member is bare.

#### Scenario: A pin in an extra to another subdirectory
- **WHEN** the `lm-studio` extra pins `troupe-runner-lm-studio-v0.1.0` with `#subdirectory=plugins/runner-ollama`
- **THEN** `scripts/check.py` fails, naming `troupe-runner-lm-studio`, the extra, `packages/troupe-run/pyproject.toml`
  and the expected reference

#### Scenario: A runner in an extra released
- **WHEN** a release pull request that releases `troupe-runner-lm-studio` at 0.1.1 is merged
- **THEN** the pinning pull request moves its pin to `troupe-runner-lm-studio-v0.1.1` in the `lm-studio` extra and in
  `all`, and changes nothing else

#### Scenario: A bare member in an extra
- **WHEN** the manifest gives `packages/troupe-run` 0.1.0, every base dependency is pinned, the `lm-studio` extra names
  `troupe-runner-lm-studio` bare, and the bundle's release configuration doesn't exclude its commits
- **THEN** `scripts/check.py` fails, naming `troupe-runner-lm-studio`, `release-please-config.json` and the exclusion
  to add

#### Scenario: A component's first release before its pin
- **WHEN** a release pull request first releases `troupe-plugin-sdk`, the bundle pins `troupe` and names the SDK
  bare, and the bundle's release configuration excludes its commits
- **THEN** the bundle check passes on it, and the pinning pull request after its merge pins the SDK
