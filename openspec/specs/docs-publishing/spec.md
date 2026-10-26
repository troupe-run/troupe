# docs-publishing Specification

## Purpose

Capability: `cap:development`, `cap:user-docs`

How a change to troupe reaches troupe.run: which pushes notify the website to rebuild `/docs`, and what the job that
sends the notice may do.

## Requirements

### Requirement: Every push to main notifies the website
After every push to `main`, the release workflow SHALL dispatch troupe-run/website's deploy workflow on its `main`, so
troupe.run rebuilds `/docs` from this repository. It SHALL dispatch after release-please has finished, whatever
release-please's result, so a tag that push released already exists when the website builds.

#### Scenario: A docs edit
- **WHEN** a pull request that edits `docs/the-company/theatres.md` merges
- **THEN** the release workflow's run on that push dispatches the website's deploy, which publishes the edit

#### Scenario: A release
- **WHEN** a release pull request merges and release-please creates `troupe-v0.1.0`
- **THEN** the dispatch comes after the tag exists, so the website builds `/docs/` from it

#### Scenario: release-please fails
- **WHEN** release-please fails on a push to `main`
- **THEN** the website is still dispatched, and builds `main`'s docs

### Requirement: The notice job can do nothing but notify
The job that sends the notice SHALL hold the `docs` environment, SHALL check nothing out and run no code from this
repository, SHALL give its own `GITHUB_TOKEN` no permissions, and SHALL use the `troupe-run-docs` App's token, minted
for troupe-run/website with "Actions: write" only, for the one dispatch.

#### Scenario: Reading the job
- **WHEN** `release.yml`'s `notify-website` job is read
- **THEN** it has `environment: docs` and `permissions: {}`, no checkout step, and two steps: minting the token and
  `gh workflow run deploy.yml -R troupe-run/website --ref main`

#### Scenario: A run on another branch
- **WHEN** the workflow runs on a ref other than `main`
- **THEN** GitHub refuses it the `docs` environment, which holds the App's key, so nothing is dispatched
