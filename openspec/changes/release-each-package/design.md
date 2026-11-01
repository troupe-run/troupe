# Design

## Context

See proposal.md for why. Today:

- `release-please-config.json` has one `linked-versions` plugin, `troupe`, over core, the six adapters, both runners
  and `troupe-run` (#215). The protocol is on its own. Every manifest version is 0.0.0, origin has no tags, and
  release pull request #89 is open, releasing all eleven components at 0.1.0.
- `packages/troupe-run/pyproject.toml` names every other workspace member bare. The root's `[tool.uv.sources]` makes
  each `{ workspace = true }`. `uv tool install "git+…@<ref>#subdirectory=packages/troupe-run"` finds the workspace
  root in that checkout, so every component comes from the same commit (install-with-uv design D1).
- `scripts/release_config.py` checks the group against `packages/*` plus what the bundle ships
  (runners-in-linked-group D1–D4). `scripts/install_check.py` expects a `troupe-run-v<version>` tag to name the
  version core declares, because the group kept them equal.
- The `release` workflow has one job that writes, `release-please`, using the release App's token, in the `release`
  environment (limited to `main`). The guard exempts a `release-please--` branch in troupe from the branch-change
  and closes-an-issue rules by its name, because a ruleset lets only the release App write those branches.

**Observed with uv 0.13.6 (2026-11-01, a local workspace of three packages, git tags over `file://`):**

1. Pins written as direct references in the bundle's `[project] dependencies`, with the root's workspace sources
   unchanged: `uv lock` and `uv sync --locked` install every member editable from the workspace. `uv.lock` records
   the members as editable, with no URL. Moving a pin to another tag leaves `uv lock --locked` passing.
2. `uv tool install "git+…@<bundle-ref>#subdirectory=packages/pbundle"` ignored the pins and installed every member
   from the bundle's commit, including an unreleased change.
3. The same command with `--no-sources` installed each member from its pinned tag's commit. A member's bare dependency
   on another member (`pb` → `pa`) was satisfied by the bundle's pin for `pa`.
4. A pin written as the member's own `[tool.uv.sources]` git entry made `uv lock` fail: "`pa` is included as a
   workspace member, but references a Git in `tool.uv.sources`. Workspace members must be declared as workspace
   sources."

## Goals / Non-Goals

**Goals:**
- A release of any component releases it alone, and is followed by a bundle that pins it, with no step to remember.
- A bundle tag installs exactly the component releases it pins. Local development and CI's per-commit install keep
  using the workspace.
- 0.1.0 goes out in two steps: the components and the protocol in #89, then `troupe-run` pinning them.

**Non-Goals:**
- Pinning commit SHAs as well as tags (#220).
- Switching the documented command from `@main` to a tag (#208). This change defines the tag's form; #208 uses it.
- Pre-release marking (#217), and moving runners out of the repository (#38, #67).

## Decisions

### D1. No linked group, one release pull request

The `linked-versions` plugin goes, and no other plugin replaces it. `separate-pull-requests` stays off (#218, 4), so
the protocol's release still can't merge apart from troupe's. The check refuses any `linked-versions` plugin rather
than only the `troupe` group, because #218 chose one rule for every package.

### D2. Pins are direct references in the bundle's dependencies

A pin is the PEP 508 form
`<name> @ git+https://github.com/troupe-run/troupe@<name>-v<version>#subdirectory=<member path>`, in `troupe-run`'s
`[project] dependencies`. The root's `[tool.uv.sources]` stays as it is, so locally the workspace wins (observation 1).

- *Alternative: the bundle's own `[tool.uv.sources]` with git entries.* uv refuses it (observation 4).
- *Alternative: version constraints (`troupe-vcs-git==0.1.1`).* These would label the release but not change what's
  installed, which is still the bundle's commit (observation 2), so unreleased commits would ship.
- The URL is the GitHub repository even though local checks install from a `file://` clone. A pin is what a
  published tag installs, and its only user is `--no-sources` (D3).

A component that has never released stays bare (for example, a new package). The pinning step pins it after its
first release (D4).

### D3. A tagged install uses `--no-sources`; a commit install doesn't

Owner, 2026-11-01. `install_check.py` gets two forms. For a `troupe-run-v<version>` tag:
`uv tool install --no-sources "git+…@troupe-run-v<version>#subdirectory=packages/troupe-run"`. For `main`, a commit
or `<commit>`: today's form. The docs check (`test_install_docs.py`) accepts each copy only in the form for its ref.
The README and install page say `@main` until #208, so their text doesn't change here.

- `--no-sources` ignores every `[tool.uv.sources]`, so a bare dependency on a workspace member would be looked up on
  a package index. The install check refuses a tag with any bare member dependency before installing (spec), and
  "Adding a package" says how a new package reaches the bundle without that (D8).
- *Alternative: the same form for every ref.* With `--no-sources`, installing `main` would install the bundle at
  `main` with released components. That would hide the unreleased work the commit form is for, and CI's
  per-commit install check.

### D4. `scripts/pin_bundle.py` moves the pins

The script uses the standard library only, like the other release scripts. It reads `.release-please-manifest.json`,
`release-please-config.json` and the bundle's `pyproject.toml`. For each workspace member in the bundle's
dependencies whose manifest version is above its pin, it rewrites that one dependency string to the pin at the
manifest version. A bare dependency counts as below any version above 0.0.0. It reads the manifest rather than the
action's outputs, because on `main` after a release the manifest *is* the latest release of each component, and a run
that was missed is caught up by the next one.

- **Surgical edits.** Only the dependency string's text between its quotes changes. Every other byte of the file,
  including comments, order and line endings, stays as it was. The file is read and written as bytes, so Windows
  tests see the same result.
- **Output.** It prints nothing and exits 0 when no pin moves. Otherwise it writes the commit message (D5) to the path
  it's given, and lists each move as `name old → new`.
- **Malformed input is an error.** A pin naming another repository or subdirectory, a pin above the manifest, or a
  changelog without a section for a version it needs: each stops the step, naming the file and the fix. It doesn't
  skip that component.

### D5. The commit type comes from the components' changelogs

For each moved pin, the script reads the sections of the component's `CHANGELOG.md` whose version is above the old
pin (any, when bare) and at most the new one. Headings are `## [x.y.z](…)` or `## x.y.z (…)`, as release-please
writes them. A `### ⚠ BREAKING CHANGES` section anywhere makes the commit breaking. A `### Features` section makes
its type `feat`, otherwise `fix`.

- Versions alone can't say this before 1.0, because a feature and a breaking change both bump the minor
  (`bump-minor-pre-major`, with no `bump-patch-for-minor-pre-major`).
- **Message.** The subject is `<type>(bundle)<!>: ship <name> <version>` for one pin, or
  `<type>(bundle)<!>: ship <n> component releases` when names won't fit in 72 characters. The body lists each
  move. For a breaking commit, a `BREAKING CHANGE:` footer names each component and version with breaking changes and
  points to its changelog, so the bundle's changelog says what broke. The script signs it off as the release App's
  bot, the identity in the config's `signoff`.
- *Alternative: read the release pull request's commits through the API.* That needs a token and network in the
  script, and it duplicates what release-please already wrote down.

### D6. The `pin-bundle` job

In `release.yml`, `pin-bundle` runs after `release-please` (`needs`). It runs only when that job's
`releases_created` output is `true`, which needs `release-please` to expose the action's output. It uses the `release`
environment, and mints the release App's token with `contents: write` and `pull-requests: write` only. It checks out
`main`, and sets up uv with the workflow's pinned action versions. It runs `uv run scripts/pin_bundle.py`, and when a
pin moved:

1. It commits as the release App's bot on `release-please--pin-bundle`, from `main`, and force-pushes (the branch is
   always one commit on `main`).
2. It opens a pull request to `main`, or, if one is open from that branch, edits its title and body to match the
   commit. The body says it was made by the release workflow, lists the moves, and closes no issue.

The branch name is under `release-please--`. troupe's ruleset lets only the release App write there, and the guard
exempts the branch by name (development-workflow.md, `commit-branch-change`, `pr-closes-issue`). So no guard or
ruleset change is needed. release-please finds its own pull request by its `release-please--branches--main` branch
and `autorelease: pending` label, which this one has neither of. The probe checks that it leaves this one alone (D9).
CI, DCO and the guard run on the pull request, because the App's token starts workflows. The owner merges it
through the queue.

- *Alternative: commit to `main` directly.* Rejected in #218: it needs a ruleset bypass.

### D7. The bundle's first release: `exclude-paths` until the first pin

Until the bundle first releases, its entry in `release-please-config.json` has
`"exclude-paths": ["packages/troupe-run"]`. release-please then skips every commit whose files are all under that
path for `troupe-run`, so #89 regenerates without it. The first pinning commit removes the key, which is the
script's only edit outside the bundle's `pyproject.toml`, and only while the key is present. Its next run counts the
bundle's whole history plus the pinning commit, with no tag, so it releases `troupe-run` at `initial-version`, 0.1.0.
The check refuses the key once the manifest gives the bundle a version above 0.0.0. While the bundle is at 0.0.0, the
check accepts only that exact value.

To verify on the probe before relying on it (D9):
- whether the path is repository-relative or package-relative;
- whether a commit that touches `packages/troupe-run/` and also a path outside every package (`uv.lock`, the root
  `pyproject.toml`) still counts for the bundle. `troupe-run`'s first commit was like that. release-please reads a
  commit as the component's when it touches the component's path, and the open question is whether
  `exclude-paths` then judges all the commit's files or only the component's.

If the probe shows such a commit still releases the bundle, the fallback is a lightweight tag `troupe-run-v0.0.0` on
`main`'s head, created once by the owner after this change merges and before #89 regenerates, with no GitHub
release, so the install check doesn't run. Check on the probe that release-please starts the bundle's commits from it.
If neither works, stop and ask the owner. This change won't ship a bootstrap that the probe hasn't shown working.

- *Alternative: let #89 include the bundle.* Its 0.1.0 would be the same commit as the components' 0.1.0, but
  unpinned, and the first pinning pull request would then make a 0.1.1 or 0.2.0 straight away. That fails #219's
  done-when.
- *Alternative: leave the bundle out of the release config until it's pinned.* This needs a permanent
  "not configured yet" case in the check and in the script, which is more code than a key that removes itself.

### D8. What the static check can and can't require

`release_config.py` refuses: any `linked-versions` plugin; a pin naming another repository, another subdirectory than
the member's, or a tag that isn't `<name>-v<semver>`; a pin above the manifest; a pin for a name that isn't a
workspace member (`bundle.py` already refuses a non-member dependency); and the bootstrap key in the wrong state
(D7).

The issue asks that "every package the bundle depends on has a pin". The check can't require that on its own. The
release pull request that first releases a component moves its manifest version above 0.0.0 one merge **before**
the pinning pull request can pin it, and CI must pass on that release pull request. So completeness is the pinning
step's job, and it runs after every release. The install check refuses a published bundle tag with a bare
component. "Adding a package" in `releasing.md` says to add a new package to the bundle's dependencies in a commit
that doesn't release the bundle (`build(bundle): …`), so its first pin, not that commit, releases the bundle.

### D9. The probe

The probe is a private `troupe-run/infra-probe-release-each-package`, deleted afterwards (troupe-run/infrastructure#217).
It holds a three-member uv workspace shaped like troupe (core, an adapter that depends on core, and a bundle that
depends on both), release-please with this change's config, and `pin_bundle.py` with the `pin-bundle` job. It uses
`GITHUB_TOKEN`, so its pull requests start no CI, which the probe doesn't need. It checks:

1. **uv:** `uv sync --locked` uses the workspace with pins in place, and the tagged `--no-sources` install from
   GitHub installs the pinned trees, on Linux, macOS and Windows (a matrix job).
2. **D7:** the first release pull request leaves out the bundle, which has a history commit touching both its path
   and `uv.lock`. Otherwise, try the fallback tag.
3. **D4–D6:** merging it opens the pinning pull request, typed `feat`, which removes `exclude-paths`. Merging that
   gives a release pull request with the bundle at 0.1.0.
4. **A component-only fix:** a `fix:` to the adapter releases the adapter alone. The pinning pull request is `fix`,
   and the bundle goes to 0.1.1. A `feat!:` to core gives a breaking pinning commit, and the bundle goes to 0.2.0.
5. release-please leaves the pinning branch and pull request alone, and a second release while a pinning pull
   request is open updates it rather than opening another.

### D10. The install check for a tag

For a `troupe-run-v<version>` ref, `install_check.py` reads the bundle's `pyproject.toml` at the resolved commit. Its
`project.version` must equal the tag's version. Every workspace member it depends on must be pinned. The version
`troupe --version` must print is `troupe`'s pinned version, not core's `pyproject.toml` at that commit. For any other
ref, it expects core's version at the commit, as now. The check uses the D3 form for the ref, both from GitHub
(`--hosted`) and from the checkout. From the checkout, the pins still fetch from GitHub, which is what the tag would
install.

## Risks / Trade-offs

- [The pinning pull request waits on the owner, so a component fix reaches tag installs one merge later] → This is
  #218's choice. Both pull requests go through the normal path, and the pinning one is opened automatically.
- [A bundle tag with a bare component installs it from a package index under `--no-sources`] → The install check
  refuses such a tag before installing and opens the Bug. "Adding a package" avoids making one (D8).
- [`exclude-paths` doesn't behave as D7 needs] → The probe decides before #89 regenerates, using the fallback tag or
  the owner's call.
- [`--no-sources` behaves differently on Windows or an older uv] → The probe's matrix covers all three OS. The
  release install check runs the exact form on every platform and Python for each tag.
- [The pinning job edits files in CI with the App's write token] → It runs only on `main`, in the `release`
  environment, and runs only this repository's script from `main`. It pushes only to its own reserved branch.
- [A release of only the protocol or the bundle] → No pin moves, so no pull request opens (spec scenario).

## Migration Plan

1. Probe (D9). Then merge this change. Its commits under `packages/troupe-run/`, if any, are typed so they don't
   release, and `exclude-paths` covers them anyway.
2. The push regenerates #89 without `troupe-run`. Check it before the owner merges.
3. The owner merges #89, and the components and protocol are tagged at 0.1.0. `pin-bundle` opens the first pinning
   pull request, which pins all nine at `-v0.1.0` and removes `exclude-paths`. The owner merges it.
4. The next release pull request releases `troupe-run` at 0.1.0. The owner merges it, and the release install check
   runs the `--no-sources` form against `troupe-run-v0.1.0` on every platform. Then #208.

Rollback: revert the change and put the linked group back. Tags are never moved, so after step 3 a revert also needs
the manifest's versions left as they are.
