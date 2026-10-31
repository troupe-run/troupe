# Design

## Context

See proposal.md, "Why". What shapes the approach:

- **The install command lives in one place.** `scripts/install_check.py` holds `TEMPLATE`, `REPOSITORY` and
  `DOCUMENTED_REFS` (`main`, `<commit>`). `scripts/tests/workspace/test_install_docs.py` fails on any
  `uv tool install "` line in `README.md`, `packages/troupe-run/README.md` or under `docs/` that isn't the template
  with one of those refs (install-with-uv design D3).
- **The install check installs from the checkout, by commit** (install-with-uv D4): a `file://` URL, so it works for a
  merge commit that was never pushed. CI runs it in every full check leg (D5). install-with-uv left the hosted URL to
  #189: "#189's release check runs the hosted URL against each tag".
- **release-please releases the linked group together.** `troupe`, `troupe-run` and the six adapters are one linked
  group, so one release pull request tags `troupe-v<v>` and `troupe-run-v<v>` on the same merge commit, with a GitHub
  release for each. The plugins and the protocol version on their own. The release workflow uses the
  `troupe-run-release` App's token, so the releases it publishes start workflows. A release made with
  `GITHUB_TOKEN` wouldn't.
- **`scripts/release_config.py` checks the bundle's entry only for its lock update** (`expected not in
  extra-files`), so more `extra-files` beside it are allowed.
- **`scripts/python_versions.py` checks only `ci.yml`'s matrix** against the supported versions.
- **No tag exists.** The manifest gives every package 0.0.0.

## Goals / Non-Goals

**Goals:**

- #208 is a one-line edit in each of two files (`@main` to `@troupe-run-v0.1.0`), with nothing else to build.
- After #208, no release needs a docs pull request to keep the documented tag current.
- Every `troupe-run` release is installed from GitHub, the way the docs say, on all three platforms, without anyone
  remembering to do it, and a failure reaches a person as an issue.

**Non-Goals:**

- Switching the docs to the tag, and seeing the check pass on a real tag (#208).
- PyPI, and other ways of reaching users (#143).
- Changing what the linked group holds. See Risks for the plugins.

## Decisions

### D1. The documented tag is the bundle's: `troupe-run-v<version>`

The owner chose this on 2026-10-31. The command installs `troupe-run`, and `troupe-run` is the name people see in
`uv tool list`, `uv tool upgrade` and `uv tool uninstall`. Its tag names the thing installed. If core and the bundle
are ever unlinked (install-with-uv's risk: the bundle's version doesn't describe its plugins), the bundle's tag is
still the right one to install, and core's might not be.

The alternative was core's `troupe-v<version>`. It matches what `troupe --version` prints, and what people will call
"troupe 0.1.0". But the docs would install `troupe-run` from a tag named for `troupe`. While the group is linked, the
two versions are equal, and the check holds them equal (D4), so the bundle's tag doesn't mislead anyone about the
version.

The prefix is held once, as `TAG_PREFIX = "troupe-run-v"` in `install_check.py`, beside `TEMPLATE`. The docs test, the
check and the workflow's filter read or repeat that one value, and the workflow's copy is checked against it (D5).

### D2. The docs test accepts the tag at the manifest's version, and nothing else

`DOCUMENTED_REFS` becomes a function of the root: `main`, `<commit>`, and `troupe-run-v<version>` with `<version>`
read from `.release-please-manifest.json` for `packages/troupe-run`. A tagged line at any other version fails,
naming the page, the line and the expected tag. While the manifest says 0.0.0, the only tag allowed is
`troupe-run-v0.0.0`, which never exists. The test refuses 0.0.0 outright, naming it as "no release yet", so a copy
can't name a tag before one exists.

Why the manifest and not `pyproject.toml`: the manifest is what release-please writes the tag from, and it's the file
the release-config check already reads. The two agree on every release commit, because release-please writes both.

The alternative was a `<tag>` placeholder, like `<commit>`. It shows the form, but it's a command that can't be
copied, and the owner asked that the README keep `@main` until the tag exists. So the docs give no tag command yet.
The prose names the form (`troupe-run-v<version>`) and points to #208.

### D3. release-please moves the documented tag (owner, 2026-10-31)

The README and `docs/opening-night/install.md` put `<!-- x-release-please-start-version -->` before the install
command's code fence and `<!-- x-release-please-end -->` after it. The bundle's entry in `release-please-config.json`
gains two `extra-files`, `{"type": "generic", "path": "/README.md"}` and the same for the install page. release-please's
generic updater replaces each version-shaped string between the markers with the bundle's new version. So a release
pull request turns `@troupe-run-v0.1.0` into `@troupe-run-v0.2.0` in the same commit as the manifest, and D2's check
passes on it. While the command says `@main`, there's nothing version-shaped between the markers, and nothing changes.

The markers go outside the fence, because a comment inside it would be shown as part of the command. The docs
already use HTML comments (`docs/prompt-book/cli.md`), so troupe.run's build handles them. Only the command's own
code block goes between the markers, so no other version on the page is touched. The `<commit>` command on the
install page stays outside: it has no version, and it must not get one.

The docs test also fails when a `uv tool install "` line with a `troupe-run-v` tag sits outside a start/end pair,
naming the page and the line. The release-config check fails when the bundle's entry doesn't list both pages,
naming the file.

**Tried before it's relied on.** Task 3.3 runs release-please's generic updater, from npm at the version the action pins,
on copies of both pages with a tag in place, and confirms it moves the tag and nothing else. The owner token
release-please's own dry run needs isn't required for that.

The alternative was a docs pull request after each release, once its check had passed. Then the docs would never name
an unchecked tag, but every release would need a follow-up, and a forgotten one leaves the docs a release behind. The
cost of this choice is in Risks.

### D4. `--hosted` installs from GitHub with the ref as given

```text
uv run scripts/install_check.py [--ref REF] [--python VERSION] [--hosted]
```

Without `--hosted`, nothing changes: the checkout's `file://` URL, with the ref resolved to a commit (install-with-uv
D4). With `--hosted`, the install URL is `REPOSITORY` with the ref exactly as given, so the check runs the command the
docs give, character for character, as `command(REPOSITORY, ref)` builds it. The ref is still resolved in the checkout,
only to read core's version at that commit, so the workflow checks out the same ref first.

When the ref matches `TAG_PREFIX` + version, that version must equal core's version at the commit, and the installed
`troupe --version` must print it. Each failure names the tag and the version found. The linked group keeps the two
equal, so a difference means the tag or the group is wrong.

A `--repository URL` option was considered. It's more general, but the only other URL anyone needs is the checkout,
which is the default. `--hosted` can't be pointed at the wrong place.

### D5. A release install check workflow

`.github/workflows/release-install-check.yml`:

- **Triggers:** `release: types: [published]`, and `workflow_dispatch` with a required `ref` input (a tag, branch or
  commit), for re-running a release's check, or trying the workflow against `main`.
- **Job `install`:** `if:` the event is the dispatch, or the release's tag starts with `troupe-run-v`. release-please
  publishes one release per component, so the others' events start the workflow but skip the job. Matrix
  `os: [ubuntu-latest, macos-latest, windows-latest]` × `python:` the supported versions, `fail-fast: false`. Steps:
  check out the ref, set up uv with that Python, then
  `uv run scripts/install_check.py --hosted --ref <ref> --python <python>`. Pinned actions, `timeout-minutes` and
  `permissions: contents: read`, as in `ci.yml`.
- **Job `report`:** `needs: install`, `if: failure()` and the ref is a `troupe-run-v` tag. It runs
  `python3 scripts/release_check_report.py`, which reads the run's jobs (`gh run view <id> --json jobs`), and opens one
  issue with type Bug, titled `Install check failed for troupe-run-v<version>`. The body lists each failed leg
  (platform and Python) with a link to its job, and links the run and the release. It says the tag and release stay
  as they are, the fix is a patch release, and the issue goes on the roadmap board by hand. Its permissions are
  `contents: read`, `actions: read` (the run's jobs) and `issues: write`, and nothing else.
- A dispatch against `main` or a commit that fails just fails the run. It isn't a published release, so it opens no
  issue.

`scripts/release_check_report.py` is standard library only, like `check_result.py`. Its body-building is a pure
function of the jobs' JSON, tested with a payload copied from a real `gh run view --json jobs`. Only opening the issue
touches the network.

`scripts/python_versions.py` checks this workflow's `python` matrix as it checks `ci.yml`'s. A workflow test checks
that its tag filter is `TAG_PREFIX`, so the prefix can't drift.

**Why a separate workflow, not a job in `release.yml`:** `release.yml` runs on every push to `main` with the release
App's key in its environment. This check needs no secrets and runs on another event. Keeping it apart keeps the
App's key away from code checked out from a tag.

**Why the event and not a step after release-please:** the event comes after the release exists. Re-running it, or
dispatching it for an old tag, needs no release machinery.

### D6. Opening a Bug, and nothing else, when a published tag fails

The owner chose this on 2026-10-31. Tags are never moved or deleted, so a broken release stays published, and the
docs (D3) already name it. Its fix is the next patch release, which moves the docs on. The workflow doesn't edit the
release's notes. That would need `contents: write` on a job running code from the tag, and the Bug is where the
failure is tracked. A run started by the release App notifies nobody, so a red run alone would go unseen.

**Issue type.** The report job sets the type when it creates the issue (`gh api` `POST /repos/{owner}/{repo}/issues`
with `type: Bug`). `GITHUB_TOKEN` with `issues: write` can set the org's issue type: checked on 2026-10-31 in a
private probe, `troupe-run/infra-probe-issue-type` (deleted afterwards), whose `workflow_dispatch` run made that same
call and opened an issue by `app/github-actions` whose type the API read back as Bug (task 4.4). The same run's
`gh run view --json jobs` listed its own running job, so the report job can read the legs before it finishes.

**The board.** `GITHUB_TOKEN` can't write the org's project, and the org adds issues to the board by hand (the
add-issues-to-the-roadmap habit), so the body says to. The sweep for issues missing from the board picks it up too.

### D7. The prose stays true in 0.1.0's own copy of the docs (owner, 2026-10-31)

troupe.run builds a copy of `/docs` for each release from its tag, and a tag never changes. At the 0.1.0 tag the
command still says `@main`, because #208 can only switch it once the tag exists, and the release pull request can't do
it: release-please rewrites version strings, `@main` has none, and only the release App may commit to that branch. So
0.1.0's copy of the install page will give the `@main` command whatever this change does.

The owner accepted that, and asked that the prose not make it worse. The README and the install page no longer say
"there's no release yet" or "from the first release". They say each release is tagged `troupe-run-v<version>`, on the
releases page, and that its tag goes in place of `main` to install it. That reads true before the release, at the 0.1.0
tag, and after #208. From the next release on, the command itself names the tag (D3).

Other options considered: having troupe.run build 0.1.0's copy from the commit #208 lands (a website change, and the
copy would no longer match its tag), and merging a docs pull request that names `@troupe-run-v0.1.0` just before the
release pull request (the docs check would have to accept a tag that doesn't exist yet, and `main` would name it for a
while).

## Risks / Trade-offs

- **[The docs name a new tag before its check has run.]** The website rebuilds `/docs` from the tag as soon as it's
  released, and the check runs after. → It's a few minutes. A failure opens a Bug at once, and the fix is a patch
  release. This is the trade the owner chose over a docs pull request per release.
- **[`release: published` from the release App doesn't start the workflow.]** Events made with an App's token do start
  workflows, unlike `GITHUB_TOKEN`'s. But nothing here can show it before 0.1.0. → #208's done-when is seeing it pass
  on the real tag. If it didn't start, `workflow_dispatch` with the tag runs the same check, and the trigger is fixed
  in #208.
- **[The workflow can't run before it's on `main`.]** `workflow_dispatch` needs the file on the default branch. →
  Before merge, `--hosted` is run locally against this branch's pushed head on macOS (task 1.4). After merge, one
  dispatch against `main` runs all three platforms (a workflow follow-up), before 0.1.0 depends on it.
- **[A plugin-only release makes no `troupe-run` tag.]** The runners aren't in the linked group (they'll move to their
  own repositories). A release that fixes only `troupe-runner-scripted` tags that plugin, and the bundle's tag, so the
  docs, doesn't move until the group next releases. → Out of scope here: it's a question about the linked group, not
  the install. Raised with the owner as a follow-up issue rather than decided here.
- **[release-please's generic updater changes more than the tag.]** → Only the command's code block sits between the
  markers, and task 3.3 runs the updater on both pages before it's relied on.
- **[An install from GitHub fails because of GitHub, not troupe.]** → The report links each failed job, so a
  transient failure can be told apart, and re-run with `workflow_dispatch`. The issue is closed with that run.

## Migration Plan

Nothing to migrate. The docs still say `@main`, and the workflow first runs when 0.1.0 is published. Rollback is
reverting the change. #208 then switches the two commands to `@troupe-run-v0.1.0`, after the release pull request
has set the manifest to 0.1.0.
