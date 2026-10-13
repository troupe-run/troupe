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

- **Core and its bundled adapters** (`packages/*`) and **the protocol** (`protocol/`) form one linked group,
  `troupe`. When any of them has a releasable commit, all of them release, at the same version. They run in-process
  together, so mixed versions would be combinations nobody tests. The protocol is a component of its own (release
  type `simple`), so a contract change releases the core and is listed in
  `protocol/CHANGELOG.md`. The protocol's version is the release it shipped in. The
  runner contract keeps its own version (version 0), set in its schemas.
- **Each plugin** (`plugins/*`) versions on its own, because plugins are meant to move to their own repositories.
- **Everything else** (`openspec/`, `scripts/`, `docs/`, the root `pyproject.toml`, CI) belongs to no component and
  releases nothing.

Each component has its own `CHANGELOG.md` in its directory. Tags are `<component>-v<version>`, for example
`troupe-v0.1.0`, `protocol-v0.1.0` and `troupe-runner-scripted-v0.1.0`.

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

## When something goes wrong

- **A wrong version or changelog in an open release pull request:** don't edit the pull request. release-please
  rewrites it on the next push. Fix the cause (a commit message on `main` can't change, so add a commit, or use
  `Release-As`).
- **A wrong release:** fix it forward with a `fix` commit, or `Release-As` for the next version. Tags are never moved
  or deleted.
- **Stopping releases:** disable the `release` workflow. Releases already made stay, because tags and changelogs
  are ordinary history.
