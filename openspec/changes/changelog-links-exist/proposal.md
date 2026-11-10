# Proposal

## Why

`docs/backstage/changelog.md` links three changelogs that don't exist yet: `plugins/runner-ollama/CHANGELOG.md`,
`plugins/runner-openai/CHANGELOG.md` and `packages/troupe-plugin-sdk/CHANGELOG.md` (#366). All three parts are at
`0.0.0` in `.release-please-manifest.json`, and release-please writes a changelog only with a part's first release,
so the links are 404s on troupe.run's `/docs/next/backstage/changelog/`. The website's weekly link check found them
(troupe-run/website#112).

The page's test, `packages/troupe/tests/test_user_docs_changelog.py`, demanded the broken links. It requires the page
to link every changelog `release-please-config.json` *will* write, whether or not it exists. website#112 adds a
build check that links from `docs/` into this repository resolve, and it can't land until `main` has no broken links.

## What Changes

- **The page links a part's changelog only once the file exists.** A part that hasn't been released is named
  without a link, as a list item that starts with its component name in code (`` - `troupe-runner-ollama` ``). The
  page's "starts with its first release" wording stays.
- **The test checks the files, not just the config.** For each part `release-please-config.json` writes a changelog
  for, the page links its changelog or names the part. A linked changelog must exist in the repository, and the
  failure says to name the part until its first release. A link to a changelog release-please doesn't write still
  fails, as now.
- **A first release doesn't fail the test.** A part the page names whose changelog now exists passes. Owner's
  decision on #366's proposal: failing would block the release pull request. Only the release App may commit to
  that pull request, and a pull request on `main` can't link a file `main` doesn't have yet. The page links the new
  changelog in a pull request after the release merges. Until then the part is named, not linked. Nothing 404s.

Not in this change: checking every GitHub link from `docs/` resolves (that's website#112's build check), and any
change to release-please or the release workflow.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `user-docs`: the changelog page links only changelogs that exist and names each unreleased part, and the docs
  check enforces both.

## Impact

- `docs/backstage/changelog.md`: the links to changelogs that don't exist on `main` become names.
- `packages/troupe/tests/test_user_docs_changelog.py`: reads which changelogs exist, and finds named parts by their
  `component` in `release-please-config.json`.
- Release pull request #263 makes the first release of all three parts. If it merges before this change, every
  changelog exists and the page keeps its links. If it merges after, a follow-up pull request links them.
- Unblocks troupe-run/website#112.
