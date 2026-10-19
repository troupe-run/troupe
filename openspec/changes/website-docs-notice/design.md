# Design

## Context

- `release.yml` runs on every push to `main`. One job, `release-please`, holds the `release` environment and the
  release App's token, and creates tags inside that run (release-automation design D5).
- troupe-run/infrastructure#110 (design D4) set up the other end:
  - the `troupe-run-docs` App holds "Actions: write" on troupe-run/website only;
  - this repository's `docs` environment is limited to `main`, and holds `DOCS_APP_CLIENT_ID` and
    `DOCS_APP_PRIVATE_KEY`;
  - tags need no rule of their own, since release-please tags inside its run on `main`.
- The website's deploy accepts `workflow_dispatch` with no inputs, builds only `main`, and checks links before
  publishing (troupe-run/website#23, its design D11).
- No workflow in this repository is tested by a unit test, and there's no YAML library to read one.

## Goals / Non-Goals

**Goals:** every push to `main` reaches troupe.run, a release included, with a token that can't do more.

**Non-Goals:**
- Waiting for the website's deploy, or reporting its result here. The deploy's outcome is the website's to show.
- A render check of a pull request's docs (deferred on #128).

## Decisions

### D1. One job, after release-please, in release.yml

`notify-website` has `needs: release-please` and `if: ${{ !cancelled() }}`:
- It runs on every push, after the push's tags exist, so one job covers both of #120's triggers, a push and a new tag.
- It runs when release-please fails, since the docs on `main` changed regardless.
- *Alternative: a separate workflow on `push: main`.* It would race release-please: the website could build before a
  new tag exists, and miss the release until the next push.
- *Alternative: a step in release-please's job.* That job holds the release App's key, and this job shouldn't share an
  environment with it.

### D2. The job holds the docs environment and nothing else

- `environment: docs` and `permissions: {}`, with no checkout. Its steps are:
  - `actions/create-github-app-token`, pinned to the SHA `release.yml` already uses, with `client-id`, `private-key`,
    `owner: troupe-run`, `repositories: website` and `permission-actions: write`;
  - `gh workflow run deploy.yml -R troupe-run/website --ref main`, with the token as `GH_TOKEN`.
- No inputs are sent: the website's deploy takes none.

### D3. How it's verified

A unit test can't run a workflow, and there's no YAML library to read one here. Instead:
- actionlint checks `release.yml` before it's committed;
- the first run on `main` after the merge must show the job passing and a `workflow_dispatch` run of the website's
  deploy, started by `troupe-run-docs`. The owner or the agent merging it checks that, and records it on
  troupe-run/website#23.

### D4. The house scenario

The website dropped its pre-alpha note (owner, troupe-run/website#23, 2026-10-20). The house page already says
"It isn't built yet", so the scenario now asks that of the page itself, which "Pages about unbuilt behaviour invent
nothing" requires of every page.

## Risks / Trade-offs

- **[Merged before the website accepts dispatches]** The job fails, but only the job: release-please has finished. →
  Merge after the website's pull request is deployed.
- **[The key is rotated or removed]** The job fails visibly in the run, and the site stays as it was. → The fix is in
  troupe-run/infrastructure's `oob/README.md`, "The docs App".
