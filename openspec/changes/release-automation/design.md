# Design

## Context

See proposal.md for why. What exists on main (69d6c27):

- **Eight workspace members** (`[tool.uv.workspace] members = ["packages/*", "plugins/*"]`): `troupe` and six
  bundled adapters under `packages/`, and `troupe-runner-scripted` under `plugins/runner-scripted/`. Each has
  `version = "0.0.1.dev0"` in its `pyproject.toml`, and `uv.lock` records the same version for each as an editable
  package. `troupe --version` reads the installed version through `importlib.metadata`. No package has a
  `__version__` to keep in step.
- `protocol/` holds the language-neutral schemas. It isn't a package, but its changes are changes to troupe's
  contract (for example `feat(runners)!: the runner contract is version 0`).
- **History:** 144 commits. All but the first five (pre-bootstrap: "Bootstrap OpenSpec", "Add Apache-2.0
  licence…") are Conventional Commits. Scopes are free-form: `openspec` 56, `guard` 21, `platform` 9, and 20
  others.
- **`main` is protected** by the `protect main` ruleset. It allows the `rebase` merge method only (squash and merge
  commits are off at repo level too). It requires linear history, and it requires eight checks: the six CI matrix
  jobs, `DCO`, and `guard (workflow rules)`. The infrastructure App bypasses it. There's no tag ruleset.
- **`guard` is delivered, not owned here.** `scripts/guard.py`, `.github/workflows/guard.yml` and the git hooks
  are listed in `.github/guard-delivery.json` and maintained in troupe-run/infrastructure. Editing them here is
  refused. `guard.py ci` checks every commit message in the range, and checks that the branch matches an OpenSpec
  change (skipped on `main`). It has no exemptions, and it never sees a PR title. `guard.yml` runs on
  `pull_request` with the default activity types, which don't include `edited`.
- **DCO** uses the org-wide config in troupe-run/.github, which exempts org members. A bot isn't a member.
- **Org Apps today:** `dco`, and `troupe-run-infrastructure` (administration, organization administration,
  workflows and contents write). OpenTofu in troupe-run/infrastructure manages repos, rulesets, environments,
  labels and App installations. By that repo's rule it never holds secret values.

## Goals / Non-Goals

**Goals:**
- Releasing takes one step: merging a PR that someone has reviewed. Nobody edits a version or changelog.
- The release PR is an ordinary PR. It passes every required check, and its only exemption is a narrow one in
  `guard`.
- A new workspace member can't be left out of releases silently.

**Non-Goals:**
- Building or publishing distributions (wheels, PyPI, brew). A GitHub release here is a tag and notes, no assets.
- Checking or restricting commit scopes (D8).
- Release candidates, pre-release channels and backports to release branches.

## Decisions

### D1. release-please, in manifest mode

release-please derives versions and changelogs from Conventional Commits, handles a monorepo with a manifest (a
version and changelog per path), has a `python` strategy that bumps `pyproject.toml`, and works through a PR, so a
release goes through the same review and required checks as any change.

Alternatives:
- **python-semantic-release** releases on push, with no PR to review. Its monorepo support needs one config and
  one run per package, with nothing linking their versions.
- **Changesets-style tools** (changesets, knope's change files) need a hand-written file per PR. That duplicates
  the commit message, which `guard` already makes structured.
- **commitizen** bumps a single version per run. Linked groups and per-package changelogs would be our own
  scripting.

Configuration: `release-please-config.json` (one entry per workspace member: `release-type: python`, its
`package-name` and `component`) and `.release-please-manifest.json` (the current version of each). It runs through
`googleapis/release-please-action`, pinned by commit SHA like every other action in this repo.

### D2. Starting at 0.1.0

`bump-minor-pre-major: true` is set at the top level, and `bump-patch-for-minor-pre-major` is left off. The
manifest starts every package at `0.0.0`, which drops the PEP 440 `.dev0` placeholder that release-please's semver
parser doesn't model. From 0.0.0, a `feat` and a breaking change both bump the minor version, so the first release
PR proposes 0.1.0. Every package already has `feat` commits.

The release PR rewrites `version` in each `pyproject.toml` from `0.0.1.dev0` to `0.1.0`. Until it merges, the
placeholder stays, so `main` never claims a version that hasn't been released.

`initial-version: "0.1.0"` is set at the top level too. Found by the dry run (task 3.1): a component with no
release yet doesn't bump from the manifest's version. It starts at `initial-version`, which defaults to 1.0.0, and
the `linked-versions` plugin takes the group's highest version, so the linked group came out at 1.0.0. With
`initial-version`, every component's first release is 0.1.0. It does nothing once a component has a release, so
there's nothing to remove afterwards.

Alternative: pin `release-as: 0.1.0` for the first release and remove it afterwards. It would add a follow-up commit
that's easy to forget, and `initial-version` makes it unnecessary.

### D3. A linked group for `packages/`, plugins on their own (owner, 2026-10-13)

The `linked-versions` plugin puts the seven `packages/*` components in one group, `troupe`. Core and its bundled
adapters run in-process together and are installed together, so different version numbers would imply
combinations nobody tests. `troupe-runner-scripted` is outside the group. Plugins speak the protocol, import nothing
of troupe's, and are meant to move to their own repos, where they'll version on their own anyway.

`protocol/` is a component of its own, `protocol`, in the same linked group (owner, 2026-10-14). It uses
release-please's `simple` release type, which writes `protocol/CHANGELOG.md`. (It would also bump a
`protocol/version.txt`, but only one that exists, and none does: the manifest and the tag hold the version.) A contract
change then bumps the whole group, because the `linked-versions` plugin releases every component of a group when
any one of them has a release, and it's listed in the protocol's own changelog, where readers of the contract look.
The release is tagged `protocol-v<version>`. The protocol's version is the release it shipped in. It isn't a
contract version: the runner contract keeps its own (version 0), set in its schemas.

Found while building it: release-please assigns a commit to a component only by the component's own path, and
v17.11.2 has no way to add paths to a component (no `additional-paths`, in its schema or source). The first plan, to
add `protocol/` to `troupe`'s paths, wasn't possible. Alternatives offered: count a `protocol/`-only commit
nowhere, so a schema-only contract change wouldn't release; or move `protocol/` under `packages/troupe/`, against
the constraint that it stays top-level and language-neutral.

`separate-pull-requests: false` (the default) keeps one release PR for all components. Tags are
`<component>-v<version>` (release-please's default for a manifest), for example `troupe-v0.1.0`, `protocol-v0.1.0` and
`troupe-runner-scripted-v0.1.0`.

Alternatives (offered to the owner): every package independent, which gives seven adapter versions that drift apart
for no user benefit; or one version for everything, which ties plugins to core, against the plan to split them out.

### D4. `uv.lock` through `extra-files`

Each package entry gets an `extra-files` entry of type `toml` for the root `uv.lock`, with the JSONPath
`$.package[?(@.name.value=='<name>')].version`. (The `.value` is how release-please's TOML parser represents a
string.) The release PR then changes exactly one line per released package in `uv.lock`. CI's `uv sync --locked` is
the proof: it fails if the lock and the workspace disagree.

Alternative: a second job that checks out the release branch, runs `uv lock`, and pushes a commit with the App's
token. It's more moving parts (a second writer on the release branch, racing release-please's own force-pushes), and
`uv lock` could also pick up unrelated resolution changes. That would break "never rewrite what nobody asked to
change". It stays the fallback if the dry run (task 3.2) shows the JSONPath doesn't match.

### D5. The `release` workflow

`.github/workflows/release.yml` runs `on: push: branches: [main]`, with `concurrency: release` and no
cancel-in-progress, so two pushes can't race to write the release PR. The job:

1. mints a token with `actions/create-github-app-token`, from the App's client ID (a repository variable) and
   private key (a secret);
2. runs release-please with that token.

The workflow's own `GITHUB_TOKEN` is `contents: read`, and every write goes through the App token. The job runs in
a `release` environment whose deployment branches are limited to `main`. The key is an environment secret, so a
workflow on any other branch can't read it.

The PR is opened by the App, so CI and `guard` trigger on it (D6). release-please force-pushes the release branch
as more commits land, and CI re-runs each time.

### D6. A dedicated, narrow release App (owner, 2026-10-13)

A new GitHub App, `troupe-run-release`, has repository permissions contents read/write, pull requests read/write,
issues read/write (release-please labels its PRs `autorelease: pending` and `autorelease: tagged`) and metadata
read. Nothing at org level. It's installed on `troupe-run/troupe` only. GitHub has no API for creating an App, so
the owner creates it by hand. troupe-run/infrastructure declares its installation on this repo, the `release`
environment with its branch policy, the client-ID variable, and the two labels. The owner sets the private key
secret, because OpenTofu never holds secret values.

Commits the App makes through the API are signed by GitHub, so they show as verified.

Done (troupe-run/infrastructure#34, PR#41, applied 2026-10-13). App ID `5300488`, client ID `Iv23liPmD0ygDtxCbwVX`
(the `RELEASE_APP_CLIENT_ID` variable), bot user `troupe-run-release[bot]` with ID `341990208`. The key is the
`release` environment's `RELEASE_APP_PRIVATE_KEY` secret. The same PR added the `release branches` ruleset (D7).

Alternative: reuse `troupe-run-infrastructure`. It would put a key that can administer the org into this repo's
secrets, for a job that only needs to write a branch, a PR and tags.

### D7. Guard changes in troupe-run/infrastructure (done: #33, #34, #42)

These are changes to `development-workflow` and `guard.py`, made there and delivered here. This repo can't edit the
delivered files.

- **The release branch passes the branch rule, narrowly** (#33, PR#37; opened by #42, PR#44). In `guard.py ci`, a
  `release-please--` branch is exempt from the branch-change rule only when all three hold:
  - it lives in a repository in `RELEASE_REPOSITORIES`, which is `troupe-run/troupe` only. For a pull request,
    that's the head repository, so a fork's branch is never exempt;
  - it adds at least one commit to `origin/main`. It's judged against `main`, not the event's range, because
    release-please force-pushes when `main` moves;
  - every commit it adds is authored by `RELEASE_AUTHOR_EMAIL`,
    `341990208+troupe-run-release[bot]@users.noreply.github.com`.

  The commit-message rule still applies to those commits, and every other rule applies unchanged.
- **The ruleset is the hard check** (#34, PR#41). A commit's author is self-declared (`git commit --author`), so the
  author check alone isn't a control. troupe's `release branches` ruleset lets only the release App create, update or
  delete a `release-please--*` branch, with no bypass, not even the owner's. That's why the exemption is opened on
  troupe only, where the ruleset holds. The author check sits on top of it.
- **A PR-title check** (owner, 2026-10-13: keep it as a backstop; done in #37). For a `pull_request` event,
  `guard.py ci` reads `pull_request.title` from the event payload and applies the same `commit_message` rule function
  to it. An event with no readable title fails. A title isn't a commit, but if squash merging is ever turned back
  on, the title becomes the commit message. Checking it from now on means turning squash on doesn't open a gap.
  `guard.yml` adds `types: [opened, edited, synchronize, reopened]`, so renaming a PR re-runs the check. Release PRs
  are titled `chore: release main`, which passes.

All of it was delivered to troupe's `main` (guard last in `dca700d`). Task 1.3 checks it on this branch after the
rebase. This repo's requirements refer to the exemption, not its mechanics (spec: `releases`, "The release pull
request passes every required check").

### D8. Scopes stay free-form (owner, 2026-10-13)

`guard`'s pattern (`[a-z0-9][a-z0-9-]*`, optional) stays as it is. A closed scope list would refuse most of the
history's scopes (`openspec`, `guard`, `workspace`), and it isn't needed for releasing: release-please assigns
commits to packages by the paths they change, not by scope. Restricting scopes to the `cap:*` labels plus a few
tooling scopes can be its own change later. The labels now exist, generated by infrastructure.

### D9. DCO sign-off on release commits

release-please's `signoff` option, set to `troupe-run-release[bot] <341990208+troupe-run-release[bot]@users.noreply.github.com>`,
adds a `Signed-off-by` line with the bot's identity (D6) to its commits. That doesn't depend on whether the DCO App
skips bots, which the org config doesn't promise.

### D10. A test that keeps the release config complete

`scripts/tests/test_release_config.py` reads the workspace member globs from the root `pyproject.toml`, expands
them, and reads each member's `[project] name`. It asserts:

- each member path has an entry in `release-please-config.json` and in `.release-please-manifest.json`, and no
  entry names a path that isn't a member, apart from `protocol`;
- each entry's `package-name` and `component` equal the project name;
- the linked group's components are exactly the `packages/*` members plus `protocol`;
- each entry's `uv.lock` extra file uses the JSONPath for its own name, and `uv.lock` has exactly one package with
  that name, so the path matches one entry;
- `protocol` has an entry with `release-type: simple` and `component: protocol`, and no `uv.lock` extra file
  (it isn't a Python package).

Each failure message names the member and the file to fix (spec: "Every workspace member is configured for
release"). It runs inside `scripts/check.py`'s `tests` gate. It uses only the standard library (`tomllib` and
`json`), like `check.py`.

### D11. Rebase merging

release-please finds the release PR it opened through its label and head branch, not through the merge commit's
shape, so the rebase-only merge works. The commits rebased onto `main` are the App's `chore: release main` commits:
Conventional, signed off, and signed by GitHub. The first real release (the workflow follow-up in tasks) verifies
the tag and release appear.

After the merge, the release branch stays. GitHub's delete-on-merge is refused on a branch the `release branches`
ruleset protects (#41's probe). That's harmless: release-please force-pushes the same branch for the next release.

## Risks / Trade-offs

- **The `uv.lock` JSONPath may not match** release-please's TOML representation. → The dry run (3.2) shows the
  diff before the workflow goes live. The test (D10) pins the path's shape, and D4's re-lock job is the fallback.
- **Release-please's commits may not carry the bot's address.** The exemption (D7) needs every commit authored by
  `341990208+troupe-run-release[bot]@users.noreply.github.com`, and only a real release PR shows what GitHub records
  for commits the App makes through the API. → If it differs, the release PR fails `guard` on the branch rule. That
  fails closed. The workflow follow-up checks the author on the first release PR. A wrong address is fixed in
  infrastructure's `RELEASE_AUTHOR_EMAIL`, not by loosening the rule.
- **The App's force-push of its branch wasn't probed** (#41 could only probe create, commit and delete). The ruleset
  has no `non_fast_forward` rule and the App bypasses it, so it should work. → The first time `main` moves while a
  release PR is open, release-please force-pushes, and the workflow follow-up checks that it succeeded and CI re-ran.
- **Changelogs leave out commits outside any package** (`openspec/`, `scripts/`, the root `pyproject.toml`, CI). →
  This is intended: they don't change what a package does. `docs`, `ci`, `test` and `chore` commits are hidden by
  release-please's default changelog sections anyway.
- **A linked release tags seven packages even when one changed.** → Accepted for D3: they ship together. The
  changelogs show which package actually changed.
- **Release-please is a dependency on a Google-maintained action.** → It's pinned by SHA, it needs only the App
  token, and its output is plain files and tags. Replacing it later changes nothing already released.
- **The first changelog is long:** every `feat` and `fix` since the bootstrap. → Accepted. It's an honest record of
  0.1.0.

## Migration Plan

1. Done: troupe-run/infrastructure delivered the guard changes (D7: #37, #44) and applied the App's environment,
   variable, labels and `release branches` ruleset (D6: #41).
2. Done: the owner created the App and set its private key as the `release` environment's secret.
3. This repo: the config, the manifest, the test and the docs, with a local dry run (3.2). Then the workflow.
4. After merge, the first push to `main` opens the release PR. CI, DCO and guard must pass on it. Merging it creates
   0.1.0.

Rollback: delete or disable `release.yml`. Versions already released stay, because tags and changelogs are plain
history. A wrong release is fixed forward with a `fix` commit, or with `release-as` for the next version. Tags are
never moved.
