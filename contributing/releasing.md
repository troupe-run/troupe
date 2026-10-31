# Releasing

troupe's versions, changelogs and releases come from the Conventional Commits on `main`. Nobody edits a version or a
changelog by hand. This page describes releasing as built by the `release-automation` change (#23). The config is
[`release-please-config.json`](../release-please-config.json), and the current versions are in
[`.release-please-manifest.json`](../.release-please-manifest.json).

## How a release happens

1. **Commits land on `main`** through reviewed pull requests, as always. `guard` already checks that each one is a
   Conventional Commit.
2. **The `release` workflow runs on every push to `main`.** It runs [release-please](https://github.com/googleapis/release-please),
   which opens a release pull request titled `chore: release main`, or updates the one that's open. The PR bumps
   versions in each `pyproject.toml` and in `uv.lock`, and adds each version's changelog entries.
3. **Merging the release pull request is the release.** release-please then tags the merge and creates a GitHub
   release for each component it released, with that version's changelog section as the notes.

The release pull request is an ordinary pull request. CI, DCO and `guard` run on it and must pass. It's opened by
the `troupe-run-release` App, not `GITHUB_TOKEN`, because a pull request opened with `GITHUB_TOKEN` starts no
workflows. Only that App can write the `release-please--*` branch it comes from, and the App's commits carry a DCO
sign-off. `guard` exempts that branch from needing an OpenSpec change of the same name, and only that rule.

## What bumps what

| Commit | Before 1.0 | From 1.0 |
|---|---|---|
| `fix:`, `perf:`, `revert:` | patch | patch |
| `feat:` | minor | minor |
| breaking (`feat!:`, or a `BREAKING CHANGE:` footer) | minor | major |

Before 1.0 a breaking change bumps the minor version (`bump-minor-pre-major`). The first release of every component is
0.1.0. `docs`, `test`, `ci`, `chore` and the other types release nothing on their own and don't appear in
changelogs.

A commit counts towards a component when it changes files under that component's directory:

- **Core and its bundled adapters** (`packages/*`) form one linked group, `troupe`. When any of them has a releasable
  commit, all of them release, at the same version. They run in-process together, so mixed versions would be
  combinations nobody tests.
- **The protocol** (`protocol/`) versions on its own (release type `simple`), because it evolves separately from the
  packages and the docs (#140). It releases only when a releasable commit changes `protocol/`, and lists those
  commits in `protocol/CHANGELOG.md`. The runner contract keeps its own version (version 0), set in its schemas.
- **Each plugin** (`plugins/*`) versions on its own, because plugins are meant to move to their own repositories.
- **Everything else** (`openspec/`, `scripts/`, `docs/`, the root `pyproject.toml`, CI) belongs to no component and
  releases nothing.

Each component has its own `CHANGELOG.md` in its directory. Tags are `<component>-v<version>`, for example
`troupe-v0.1.0`, `protocol-v0.1.0` and `troupe-runner-scripted-v0.1.0`.

### The protocol version troupe ships

The troupe package carries a copy of `protocol/schemas/` (`packages/troupe/src/troupe/protocol/`), and records which
protocol release that copy is in `version.json` beside it. The protocol's release entry updates that file
(`extra-files`), so the release pull request that bumps the protocol rewrites it in the same commit as the manifest.
`scripts/check.py` fails if it differs from the protocol's version in `.release-please-manifest.json`. A segment's
header and `troupe --version` both read it.

A schema change touches the copy too, so it releases both the protocol and the `troupe` group. For the recorded
version to be true of a released troupe, **a commit that changes a schema is `feat`, `fix` or breaking**, never
`docs`, `refactor` or another type that releases nothing: otherwise troupe would ship changed schemas under the old
protocol version. Between releases, a checkout records the last protocol release even if its schemas have moved on.

### Scopes don't choose components

A commit's scope (`feat(cli): ...`) is free-form, and release-please ignores it when assigning commits. Only the paths
a commit changes decide which components it counts towards. A commit that changes two packages counts towards both.

## Adding a package

A new workspace member needs an entry in `release-please-config.json` and in `.release-please-manifest.json` (at
`"0.0.0"`). A `packages/*` member also goes in the `troupe` linked group. `scripts/check.py` fails until it's
configured, and its message names the member and the file to add it to (`scripts/release_config.py`).

## Forcing a version

To release a specific version instead of the computed one, add a commit whose body has a `Release-As: <version>`
footer, for example `chore: release 0.4.0` with `Release-As: 0.4.0`. To pin one component in the config instead, set
`release-as` on its entry, and remove it after that release.

## Checking each release's install

People install a release with the command in the README and the [install page](../docs/opening-night/install.md),
which names the bundle's tag, `troupe-run-v<version>` (install-from-tag design D1). Two things keep that command
working for every release:

- **Each release pull request moves the tag.** The bundle's entry in `release-please-config.json` runs release-please's
  generic updater on both pages, which rewrites the version between their `x-release-please-start-version` and
  `x-release-please-end` markers. So the release pull request that releases `troupe-run` at 0.2.0 changes
  `@troupe-run-v0.1.0` to `@troupe-run-v0.2.0` in the same commit as the versions. While the command says `@main`
  (until #208 switches it after 0.1.0), there's nothing for it to change. The docs check fails if a command names a
  tag at any version but the bundle's in `.release-please-manifest.json`, or sits outside the markers.
- **Each published release is installed on every platform.** When release-please publishes the `troupe-run-v*`
  release, the [`release install check`](../.github/workflows/release-install-check.yml) workflow runs the
  documented command from GitHub against the tag, on Linux, macOS and Windows and every supported Python, and runs
  a scripted performance with the installed `troupe` (`uv run scripts/install_check.py --hosted --ref <tag>`). The
  other components' releases start it too, but it does nothing for them.

**If it fails,** it opens a Bug titled `Install check failed for troupe-run-v<version>`, naming each failed platform
and Python, the run and the release. The workflow can't add it to the roadmap board, so add it by hand. The tag and
its release stay as they are, and the docs already name it. Fix it forward in a patch release, whose release pull
request moves the documented tag on. If a leg failed because of GitHub rather than troupe, re-run the check, and close
the Bug with that run:

```sh
gh workflow run release-install-check.yml -f ref=troupe-run-v<version>
```

The same command with `-f ref=main`, or a commit, tries the check against unreleased work. That opens no issue
when it fails.

## When something goes wrong

- **A wrong version or changelog in an open release pull request:** don't edit the pull request. release-please
  rewrites it on the next push. Fix the cause (a commit message on `main` can't change, so add a commit, or use
  `Release-As`).
- **A wrong release:** fix it forward with a `fix` commit, or `Release-As` for the next version. Tags are never moved
  or deleted.
- **Stopping releases:** disable the `release` workflow. Releases already made stay, because tags and changelogs
  are ordinary history.
