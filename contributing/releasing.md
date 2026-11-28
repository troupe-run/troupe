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
   release for each component it released, with that version's changelog section as the notes. **Until 1.0, each
   release is a pre-release,** because 1.0 holds the stability promise (#217), so GitHub shows no Latest release
   until then. The top-level `prerelease` setting does it, and release-please applies it only to a version whose
   major is 0, so it stops by itself when a component reaches 1.0, with nothing to turn off. It's read only when
   the releases are created, so the release pull request doesn't show it. `scripts/check.py` fails if it's
   removed, or set on one component's entry.

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
changelogs. The config's `changelog-sections` does that: it shows `feat`, `fix`, `perf` and `revert` and hides the
other types, and release-please releases a component only when its changelog section would list something. A
breaking change of a hidden type, such as `refactor!:`, is still listed, under breaking changes, and releases.
`scripts/check.py` fails if the sections change, or if a component's entry sets its own.

A commit counts towards a component when it changes files under that component's directory:

- **Every package versions on its own** (#218): core (`packages/troupe`), each adapter, each runner plugin and the
  bundle `troupe-run`. A `fix:` that changes only `packages/troupe-vcs-git/` releases `troupe-vcs-git` alone. There's
  no linked group, and `scripts/check.py` refuses one. A release pull request still gathers every component with
  releasable commits, so releases close together roll up into one.
- **The bundle follows** each release of anything it ships, through the pinning pull request (below), so a fix to
  one adapter still reaches everyone who installs a `troupe-run` tag.
- **The protocol** (`protocol/`) versions on its own (release type `simple`), because it evolves separately from the
  packages and the docs (#140). It releases only when a releasable commit changes `protocol/`, and lists those
  commits in `protocol/CHANGELOG.md`. The runner contract keeps its own version (version 0), set in its schemas.
- **Everything else** (`openspec/`, `scripts/`, `docs/`, the root `pyproject.toml`, CI) belongs to no component and
  releases nothing.

Each component has its own `CHANGELOG.md` in its directory. Tags are `<component>-v<version>`, for example
`troupe-v0.1.0`, `protocol-v0.1.0` and `troupe-runner-scripted-v0.1.0`.

### Records an older troupe wrote

**Before 1.0, troupe may refuse records an older troupe wrote, without migrating them.** When it does, it says so
clearly and says how to fix it: the refusal names the record, says which change it predates, and gives the fix, as
any malformed input does. It never crashes, guesses a value, or skips the record silently. The change that does it is
a breaking release (`!`, or a `BREAKING CHANGE:` footer).

So a schema change that makes a field required makes it required everywhere, in what troupe writes and what it reads
back. There's no lenient "absent: recorded before this change" form. The owner decided this on 2026-11-28
([troupe#124](https://github.com/troupe-run/troupe/issues/124)), building on 2026-11-07's ruling on
[#296](https://github.com/troupe-run/troupe/issues/296) that schemas aren't made flexible for records that don't
exist. The rule may get firmer as 1.0 nears.

### The protocol version troupe ships

The troupe package carries a copy of `protocol/schemas/` (`packages/troupe/src/troupe/protocol/`), and records which
protocol release that copy is in `version.json` beside it. The protocol's release entry updates that file
(`extra-files`), so the release pull request that bumps the protocol rewrites it in the same commit as the manifest.
`scripts/check.py` fails if it differs from the protocol's version in `.release-please-manifest.json`. A segment's
header and `troupe --version` both read it.

A schema change touches the copy too, so it releases both the protocol and `troupe`. For the recorded
version to be true of a released troupe, **a commit that changes a schema is `feat`, `fix` or breaking**, never
`docs`, `refactor` or another type that releases nothing: otherwise troupe would ship changed schemas under the old
protocol version. Between releases, a checkout records the last protocol release even if its schemas have moved on.

### Scopes don't choose components

A commit's scope (`feat(cli): ...`) is free-form, and release-please ignores it when assigning commits. Only the paths
a commit changes decide which components it counts towards. A commit that changes two packages counts towards both.

### How commits reach changelogs

release-please reads `main` back to the last release, at most 1000 commits (`commit-search-depth`), in pages of 100
(`commit-batch-size`, the most GitHub allows). For most commits it asks GitHub which files that commit changed. For
a pull request's last commit, though, it takes the whole pull request's files when no other commit of that pull
request is on the same page: that's how it recognises a squash merge. Our pull requests land by rebase, so when a
pull request's commits fall on two pages, its last commit is listed under every component the pull request changed,
and which commits that hits changes as `main` grows.

Pages of 100 make that rare, and impossible while fewer than 100 commits land between two releases, because they all
fit on one page. #223 records why that was chosen over fixing it, and when to revisit. Before merging a release pull
request, check that each changelog entry is under a component its commit changed: the check is in
[#89's comment](https://github.com/troupe-run/troupe/pull/89#issuecomment-6552218406). `scripts/check.py` fails if
either setting changes.

## The bundle follows its components

`troupe-run` names each component it ships, either bare or pinned at a release tag
(`troupe-vcs-git @ git+https://github.com/troupe-run/troupe@troupe-vcs-git-v0.1.1#subdirectory=packages/troupe-vcs-git`).
Locally the root's workspace sources win, so `uv sync` and every test use the checkout's packages, whatever the pins
say, and moving a pin doesn't change `uv.lock`.

1. **A release pull request releases components.** Merging it tags them, as above.
2. **The `release` workflow opens the pinning pull request.** Its `pin-bundle` job runs
   [`scripts/pin_bundle.py`](../scripts/pin_bundle.py) on `main`. That moves every pin that's behind its component's
   version in the manifest, a bare one included, and commits as the release App on `release-please--pin-bundle`. Like
   release-please's own branch, the guard exempts it by name. If one is already open, a later release updates it.
3. **Its commit type is the largest change it ships.** The script reads each component's changelog sections above
   the old pin. A `⚠ BREAKING CHANGES` section makes the commit breaking (its `BREAKING CHANGE:` footer names each
   one), a `Features` section makes it `feat`, and otherwise it's `fix`.
4. **The owner merges it** through the queue like any pull request. The next release pull request then releases
   `troupe-run` at that size, and its tag is what the install command names, unless a component is still bare
   (below).

Nothing moves after a release of only the protocol or the bundle, and the job opens nothing. If the job fails (for
example, a changelog without the released version's section), it says which file. Fix the cause, and the next
release's run moves every pin that's still behind.

**The bundle doesn't release while it names a component bare.** A bundle released then would send `--no-sources`
looking for that component on a package index, where it isn't, or where someone else has registered the name (#262).
So while `troupe-run` names any workspace member bare, its entry has `"exclude-paths": ["packages/troupe-run"]`,
which keeps its commits out of release pull requests. `scripts/check.py` enforces it both ways: it fails on a bare
member without the key, naming the member, and on the key with nothing bare (`scripts/release_config.py`). The
pinning pull request removes the key when it pins the last bare component, and says in its message when it leaves
one bare. Once the key goes, release-please reads the bundle's commits since its last release again, pinning commits
included, so the bundle releases at the size of the largest change it ships. The bundle's first release worked this
way: every component was bare until the first pinning pull request pinned them all, and its merge released
`troupe-run` at 0.1.0.

## Adding a package

A new workspace member needs an entry in `release-please-config.json` and in `.release-please-manifest.json` (at
`"0.0.0"`). `scripts/check.py` fails until it's configured, and its message names the member and the file to add it
to (`scripts/release_config.py`).

Dependabot must ignore it too. A member's version moves only through its own release, but Dependabot reads every
member as a dependency and looks it up on PyPI. When a package there has the same name (`troupe` does, and it's
someone else's), Dependabot asks uv to lock the member at that version, which can't resolve, and its `uv` run fails
(#254). troupe's `uv` entry in `.github/dependabot.yml` ignores `troupe` and `troupe-*`, so a member named
`troupe-<name>` is covered already. For any other name, add it to troupe's `uv` ignores in troupe-run/infrastructure's
`tofu/dependabot.json`, which delivers the file. `scripts/check.py` fails until the delivered file covers every member
(`scripts/dependabot_members.py`).

If `troupe-run` ships it, add it to the bundle's dependencies bare, and in the same commit add
`"exclude-paths": ["packages/troupe-run"]` to `troupe-run`'s entry, unless it's already there. `scripts/check.py`
fails without it, naming the member. After the package's first release, the pinning pull request pins it, removes the
key and releases the bundle (above).

Add it to `quality-gates.toml` as `[coverage.packages.<name>]`, with `paths` set to its directory and no `baseline` yet.
CI's coverage leg fails on any source file in no package, and holds a package with no baseline to the floor (80%).
Record its baseline once the leg has measured it ([quality-gates.md](quality-gates.md#adding-a-package-or-a-runner)).

## Forcing a version

To release a specific version instead of the computed one, add a commit whose body has a `Release-As: <version>`
footer, for example `chore: release 0.4.0` with `Release-As: 0.4.0`. To pin one component in the config instead, set
`release-as` on its entry, and remove it after that release.

## Checking each release's install

People install a release with the command in the README and the [install page](../docs/opening-night/install.md),
which names the bundle's tag, `troupe-run-v<version>` (install-from-tag design D1). For a tag the command carries
`--no-sources`: `uv tool install --no-sources "git+https://github.com/troupe-run/troupe@troupe-run-v<version>#subdirectory=packages/troupe-run"`.
Without it, uv applies the tag's own workspace sources and installs every component from the bundle's commit,
ignoring the pins. Installing `main` or a commit keeps the plain form, which installs everything from that commit.
The docs check refuses a tag without the flag. Two things keep the command working for every release:

- **Each release pull request moves the tag.** The bundle's entry in `release-please-config.json` runs release-please's
  generic updater on both pages, which rewrites the version between their `x-release-please-start-version` and
  `x-release-please-end` markers. So the release pull request that releases `troupe-run` at 0.2.0 changes
  `@troupe-run-v0.1.0` to `@troupe-run-v0.2.0` in the same commit as the versions. Both pages name the tag from
  0.1.0 on (#208). The docs check fails if a command names a tag at any version but the bundle's in
  `.release-please-manifest.json`, or sits outside the markers. It also fails if either page gives `@main` once the
  manifest has a release, since a release would then have nothing to move.
- **Each published release is installed on every platform.** When release-please publishes the `troupe-run-v*`
  release, the [`release install check`](../.github/workflows/release-install-check.yml) workflow runs the
  documented command from GitHub against the tag, on Linux, macOS and Windows and every supported Python, and runs
  a scripted performance with the installed `troupe` (`uv run scripts/install_check.py --hosted --ref <tag>`).
  `troupe --version` must print the version the tag pins core at, since the bundle and core version on their own.
  The check refuses a tag whose bundle leaves a component unpinned before installing anything. A pre-release starts
  it like any other published release. The other components' releases start it too, but it does nothing for them.

**If it fails,** it opens a Bug titled `Install check failed for troupe-run-v<version>`, naming each failed platform
and Python, the run and the release. The workflow can't add it to the roadmap board, so add it by hand. The tag and
its release stay as they are, and the docs already name it. Fix it forward in a patch release, whose release pull
request moves the documented tag on. If a leg failed because of GitHub rather than troupe, re-run the check, and close
the Bug with that run. Each install retries a package index that fails for about two minutes first (`HTTP_RETRIES` in
`scripts/install_check.py`), so a leg that names a network fault has already outlasted a short outage. A re-run that
fails while the Bug is open comments on it rather than opening another:

```sh
gh workflow run release-install-check.yml -f ref=troupe-run-v<version>
```

The same command with `-f ref=main`, or a commit, tries the check against unreleased work. That opens no issue
when it fails.

## Repairing a missing release

After every run, the `release` workflow's `release-tags` job checks that each version in
`.release-please-manifest.json` has its tag `<component>-v<version>` ([`scripts/release_tags.py`](../scripts/release_tags.py)).
A member at `0.0.0` hasn't released and needs none. When the job fails, it names each missing tag: a release pull
request moved the manifest, but no release was made for that component. The check fails on every push until the
release exists.

**Find out why first.** In the failed run's `release-please` job, the merged release pull request's log has a
`Building release for path: <path>` line for each component. A missing component is followed by
`Pull request contains releases, but not for component: <component>`. The usual cause is release-please reading its
own notes back. After a merge, it parses the release pull request's body, writes it back out and parses it again.
The first parse decodes the changelog's escaped `&lt;` and `&gt;`, so text like `<NAME>` in a commit subject
reaches the second parse as an HTML element. That element can take in the blocks after it (#484, where
troupe-runner-ollama 0.1.0 and protocol 0.2.0 went missing). The guard refuses such text in a commit message
(troupe-run/infrastructure#364). Backticks don't protect it, because the parse is HTML, not Markdown.

**Route 1: let release-please make it.** It releases a merged pull request labelled `autorelease: pending`, from the
pull request's body as it is now. The owner:

1. Edits the merged release pull request's body down to the missing components' blocks. Keep release-please's shape:
   a header line, a line `---`, each component as `<details><summary><component>: <version></summary>` with its
   changelog section and `</details>`, then `---` and the footer. Escape each `&lt;` and `&gt;` in the notes twice
   more (`&amp;amp;lt;`), because release-please decodes once per parse. Then
   `gh pr edit <n> --body-file <file>`.
2. Relabels it: `gh pr edit <n> --remove-label "autorelease: tagged" --add-label "autorelease: pending"`.
3. Re-runs the release run that merged it (`gh run rerun <run>`), or lets the next push to `main` run it.

Before step 1, check the body with release-please's own parser, at the version `release.yml` pins: parse it, write it
back out with `toString()`, parse it again, and confirm each missing component comes out with the notes you expect.
Only the components in the body are released, and release-please skips a release whose tag already exists. A
release run then makes them, and pins the bundle if any is a bundle member, as after any release.

**Route 2: make it by hand.** If route 1 can't be made to parse, create each release as release-please would:

```sh
gh release create <component>-v<version> --target <the release pull request's merge commit> --prerelease \
  --title "<component>: v<version>" --notes-file <that version's section of the component's CHANGELOG.md>
```

The tag is permanent, so check the target commit and the notes before running it. Pre-release applies until the
component reaches 1.0, as above. A release made by hand doesn't run `pin-bundle`. The next release run pins it,
or the pinning pull request may already name it, since the script reads the manifest.

For the `--notes-file` in the command above, `python3 scripts/release_notes.py --section <component>-v<version>`
prints that version's changelog section.

## Repairing a release's notes

After every run, the `release` workflow's `release-notes` job checks each tag the manifest's versions name
([`scripts/release_notes.py`](../scripts/release_notes.py)). Each must have a published release whose notes are that
version's section of the component's `CHANGELOG.md`, apart from the date at the end of the heading. The changelog
is dated when the release pull request was written, and the release when it merged. When the job fails, it names
each release that differs and the first line that differs. Like `release-tags`, it fails on every push until the
notes are repaired.

**Find out why first.** When the job says the notes hold U+FFFD, the release pull request's body overflowed. Past
65,536 characters, release-please saves the body to `release-notes.md` on the
`release-please--branches--main--release-notes` branch and puts a link in the pull request. release-please 17.6.0
writes that file keeping only the low byte of each character, and reads it back as UTF-8. So every character above
U+00FF, such as the ⚠ in `### ⚠ BREAKING CHANGES`, is published as U+FFFD. That's how six 0.2.0-era releases lost
their ⚠ (#486). Notes that run on past their section into other components' blocks come from the `<NAME>` parse in
[Repairing a missing release](#repairing-a-missing-release). The changelog is written separately, as UTF-8, so it's
the copy to trust.

**Repair: publish the changelog section.** Editing a published release is the owner's to do. It changes the notes
only, never the tag:

```sh
python3 scripts/release_notes.py --section <tag> > notes.md
gh release edit <tag> -R troupe-run/troupe --notes-file notes.md
```

The heading then carries the changelog's date, which the check allows. Re-run the failed `release-notes` job, or
let the next push run it.

## When something goes wrong

- **A wrong version or changelog in an open release pull request:** don't edit the pull request. release-please
  rewrites it on the next push. Fix the cause (a commit message on `main` can't change, so add a commit, or use
  `Release-As`). An entry under a component its commit didn't change comes from the page boundary ("How commits
  reach changelogs"): land any commit on `main`, which rebuilds the pull request, and comment on #223.
- **A release that was never made** (the `release-tags` job fails): see
  [Repairing a missing release](#repairing-a-missing-release).
- **Release notes that differ from the changelog** (the `release-notes` job fails): see
  [Repairing a release's notes](#repairing-a-releases-notes).
- **A wrong release:** fix it forward with a `fix` commit, or `Release-As` for the next version. Tags are never moved
  or deleted.
- **Stopping releases:** disable the `release` workflow. Releases already made stay, because tags and changelogs
  are ordinary history.
