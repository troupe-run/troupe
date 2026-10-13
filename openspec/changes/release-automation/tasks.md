# Tasks

## 1. Prerequisites in troupe-run/infrastructure and with the owner

- [x] 1.1 Open the infrastructure prerequisites as Feature issues, each linking troupe-run/troupe#23:
  troupe-run/infrastructure#33 (the guard's release-branch exemption and PR-title check, design D7), #34 (the release
  App's declarations and the `release branches` ruleset, design D6 and D7), and #42 (opening the exemption once the
  ruleset is applied). Verify each issue's body links #23 and #23 lists all three as blocking it. Done 2026-10-14:
  all three link #23, are #23's blockers, and are closed by PR#37, PR#41 and PR#44
- [x] 1.2 Owner: create the `troupe-run-release` App with exactly the permissions in design D6, install it on
  `troupe-run/troupe` only, and set its private key as the `release` environment's secret `RELEASE_APP_PRIVATE_KEY`.
  Verify with `gh api orgs/troupe-run/installations` (the App lists contents, pull_requests and issues write plus
  metadata read, with selected repositories) and `gh api repos/troupe-run/troupe/environments/release/secrets`
  (the secret's name is listed). Record the bot's user ID for 2.1. Done 2026-10-14: App 5300488, those four
  permissions, `selected`; the secret is listed; `gh api 'users/troupe-run-release%5Bbot%5D'` gives ID 341990208
- [x] 1.3 Rebase this branch onto `main`, which carries the delivered guard (`dca700d`). Verify the delivered
  `scripts/guard.py ci` with `--repository` against a scratch `release-please--branches--main` range, for each case
  in design D7: commits authored only by the bot with `troupe-run/troupe` passes; the same with another repository
  fails `commit-branch-change`; a commit by any other author fails it; and a PR title that isn't a Conventional Commit
  fails `commit-message`. Record the output in the PR. Done 2026-10-14: rebased onto `dca700d`; the four cases gave
  exit 0, then exit 1 `commit-branch-change` twice, then exit 1 `commit-message` (table for the PR description)

## 2. Release configuration and its test

- [x] 2.1 Add `release-please-config.json` and `.release-please-manifest.json` (design D1 to D4, D9). Eight package
  entries, each with `release-type: python`, `package-name` and `component` set to the project name, and the
  `uv.lock` extra file for its own name. A `protocol` entry with `release-type: simple` and `component: protocol`
  (design D3). Top level: `bump-minor-pre-major: true`, `signoff` as in design D9, and the `linked-versions` plugin
  grouping the seven `packages/*` components and `protocol` as `troupe`. Every manifest version is `0.0.0`. Verify both files parse
  (`python -m json.tool`)
- [x] 2.2 Add `scripts/tests/test_release_config.py` (design D10). Add one test for each assertion, each named for
  the property its body checks. Each one first runs against a temporary copy of the config with that one property
  broken, and then against the real files. Verify through `uv run scripts/check.py` that every test passes on the
  real files, and that each broken copy fails with a message naming the member and the file
- [x] 2.3 Write `docs/releasing.md`. Cover how a release happens (merging the release PR), what bumps what (pre-1.0
  rules, the linked group, plugins on their own, the protocol in the linked group with its own changelog), why
  scopes don't select packages, how to force a version (`release-as`), and the rollback and fix-forward rule. Link
  it from `README.md`. Verify every config key the doc names exists in `release-please-config.json`. Done
  2026-10-14: `bump-minor-pre-major` is in the config; `release-as` is described as optional and added only for one
  release, and exists in release-please's schema and source

## 3. Dry run before anything writes

- [x] 3.1 Run release-please locally, without writing (`npx release-please@<pinned> release-pr --dry-run --repo-url
  troupe-run/troupe --target-branch main` with a read-only token), against this branch's config pushed to a scratch
  ref. Verify it reports one PR titled `chore: release main`. Done 2026-10-14, against `release-automation` itself
  rather than a scratch ref (owner's choice: the branch had to be pushed for the PR anyway), with the owner's `gh`
  token and `--dry-run`, which writes nothing; no read-only token was to hand. One PR, `chore: release
  release-automation`, which is `chore: release main` on `main`
- [x] 3.2 From that dry run, verify that every package goes to 0.1.0 (design D2), that the seven `packages/*` share it
  (D3), that a `protocol/`-only commit appears in `protocol/CHANGELOG.md` and the protocol shares the group's
  version (D3), and that the `uv.lock` diff changes exactly one `version` line per package (D4). Apply each fallback
  the design names (`release-as` for D2, the re-lock job for D4) only if its check fails, and record which one ran
  in the PR. Done 2026-10-14. The first run proposed 1.0.0 for the linked group, so `initial-version: "0.1.0"` was
  added (design D2); the re-run gives all nine components 0.1.0. Applying release-please's own updaters to this
  branch changes exactly one `version` line per package in `uv.lock` (eight), and `uv lock --check` passes on the
  result; the `__init__.py` files are unchanged. No commit in the history touches only `protocol/`, so that exact
  case wasn't observable: `protocol/CHANGELOG.md` lists the 24 changes from commits touching `protocol/`, the
  protocol shares the group's 0.1.0, and linked-versions releases every group member when any has a release (its
  source). Neither named fallback ran: `initial-version` replaced D2's `release-as`, and D4's re-lock job wasn't
  needed

## 4. The release workflow

- [x] 4.1 Add `.github/workflows/release.yml` (design D5): runs on push to `main`, `concurrency: release` without
  cancelling, `permissions: contents: read`, the `release` environment, `actions/create-github-app-token` and
  `googleapis/release-please-action` pinned by commit SHA with the version in a comment, as `ci.yml` does. Verify
  with `actionlint`, or `uvx zizmor` if `actionlint` isn't available, and that every `uses:` is pinned to a
  40-character SHA. Done 2026-10-14: actionlint isn't installed, and `zizmor` reports no findings; both `uses:` are
  pinned to 40-character SHAs (`create-github-app-token` v3.3.0, `release-please-action` v5.0.0, which bundles
  release-please 17.6.0: the updaters were re-run with 17.6.0 and give the same versions and `uv.lock`)
- [ ] 4.2 Verify the whole change with `uv run scripts/check.py` locally, and that CI passes on Linux, macOS and
  Windows on the PR, together with `DCO` and `guard`. The PR closes troupe-run/troupe#23

## Workflow follow-up

- Archive the change on the branch before merging (`/opsx:archive`), so the PR lands code, docs and specs together.
- After the merge, check that the push to `main` opens the release PR as the App, that CI, DCO and guard all run and
  pass on it, and that `uv sync --locked` passes there (spec: `releases`).
- On that release PR, check that every commit is authored by
  `341990208+troupe-run-release[bot]@users.noreply.github.com` (`gh pr view <n> --json commits`). If the address
  differs, `guard` fails closed, and the fix is infrastructure's `RELEASE_AUTHOR_EMAIL` (design Risks).
- The first time `main` moves while the release PR is open, check that release-please force-pushed its branch and
  CI, DCO and guard re-ran. #41 couldn't probe the App's force-push (design Risks).
- Merge the release PR, then check that the tags `troupe-v0.1.0` (and the six other `packages/*` tags) and
  `troupe-runner-scripted-v0.1.0` exist with GitHub releases, and that `troupe --version` on `main` prints 0.1.0.
- Comment on troupe-run/troupe#23 with the PR, the archived change and the first release, then close it.
