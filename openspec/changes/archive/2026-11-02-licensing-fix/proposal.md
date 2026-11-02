# Proposal

## Why

`docs/backstage/licensing.md` ends its source paragraph with "There's nothing to install yet." That stopped being
true when `troupe-run-v0.1.0` was published, and the install page now gives the command for it. troupe.run renders the
page at /docs/backstage/licensing/ and /docs/next/backstage/licensing/. Once troupe-run/website#83 tells visitors
troupe can be installed, this page would be the only one on the site saying otherwise, and the website can't fix
it, because its docs are generated from troupe's `docs/` (#237).

## What Changes

- **The licensing page points to the install page instead.** "There's nothing to install yet." becomes "You can
  install it from a release ([Install](../opening-night/install.md))." The owner chose this over deleting the
  sentence (2026-11-02), because it takes a reader from the source to an install.
- **The link uses the docs' `.md` form**, as other pages do (for example
  `stagecraft/bring-your-own-agent.md`), not the rendered `../opening-night/install/` URL that #237 gives. The
  user-docs requirement "Links between pages resolve" checks a relative `.md` link. It can't check a site URL.
- **The page names no version.** A release pull request moves the version on the install page, but nothing would
  move a version here, so naming one would go stale.
- Nothing else on the page changes. `status: written` and `prerelease: false` stay: installing from a release is
  something you can already do.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. This corrects one sentence of the docs and changes no requirement. `user-docs` already covers the link
through "Links between pages resolve". The change sets `skip_specs: true`, as the docs-only
align-readme-description did.

## Impact

- `docs/backstage/licensing.md`: one sentence.
- troupe.run's licensing pages pick it up at the website's next docs build. The website repository doesn't change.
- No code, test, spec or protocol changes. `grep -rni "nothing to install"` over `README.md`, `docs/` and the
  package READMEs finds this sentence and nothing else.
