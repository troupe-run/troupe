# Proposal

## Why

troupe.run's `/docs` is built from this repository's `docs/`, one version per release (#120, troupe-run/website#23).
The site rebuilds when its own repository changes, so an edit here would wait for an unrelated website change before
anyone saw it. troupe-run/website#23 owns both ends of the trigger, and its credential is in place: the
`troupe-run-docs` App, which can only start workflows in troupe-run/website, with its key in the `docs` environment
(troupe-run/infrastructure#109 and #110). This is troupe's end.

The website has also stopped showing a pre-alpha note on docs pages (owner, 2026-10-20, troupe-run/website#23). One
scenario in this repository's `user-docs` spec relied on that note.

## What Changes

- **`release.yml` gains a `notify-website` job.** It runs after `release-please` on every push to `main`, so a tag that
  push released already exists when the website builds. It runs even when release-please fails, since `main`'s docs
  changed either way. It holds the `docs` environment, checks nothing out, and uses the App's token only to dispatch
  the website's deploy (troupe-run/infrastructure design D4).
- **`user-docs`' house scenario** no longer says the site marks the page as intended behaviour. The page says so
  itself, which every page about unbuilt behaviour already has to do. `prerelease` stays in the page contract.

## Capabilities

### New Capabilities

- `docs-publishing`: how a change to troupe reaches troupe.run, meaning which pushes notify the website, and the limits
  on the job that sends the notice.

### Modified Capabilities

- `user-docs`: the house scenario of "Pages about unbuilt behaviour invent nothing" stops relying on a site note.

## Impact

- `.github/workflows/release.yml` gets one job. No code, test or package changes, and no new secret: the key was set
  on 2026-10-19.
- **Order:** this merges after troupe-run/website#23's pull request is deployed, so the first dispatch finds the
  website's `workflow_dispatch`. Before that, the job would fail, but only the job: release-please has finished by
  then.
- **Rollback:** remove the job.
