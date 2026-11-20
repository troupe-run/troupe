# Design

## Context

See proposal.md, "Why". The release workflow (`.github/workflows/release.yml`) has three jobs: `release-please`
(opens the release pull request, or releases a merged one), `pin-bundle` (after a release) and `notify-website`
(after every push). release-please reports success when it skips a component, so nothing in the run marks the
release as incomplete. It logs "Pull request contains releases, but not for component", but it also logs that for
every component a release pull request didn't bump.

The manifest moves only through a merged release pull request. After any run on `main`, each version in it should
therefore have a tag: from that run, or from an earlier one. `release-please-config.json` names each path's
`component`, and `include-component-in-tag` is set, so a tag is `<component>-v<version>` (`releasing.md`).
`scripts/release_config.py` already holds the file names and the shared readers. `scripts/pin_bundle.py` is the
pattern for a standard-library script the release workflow runs.

## Goals / Non-Goals

**Goals:**

- A run that leaves a manifest version without its tag fails, on the push where it happened, naming the tags.
- The check works the same whatever the cause: a dropped block, a failed API call partway through, or a release
  deleted by hand.

**Non-Goals:**

- Repairing anything automatically. The notes and the target commit need a person's judgement, and a tag is never
  moved or deleted, so a wrong automatic release can't be undone.
- Checking that the tag is on the right commit, or that a GitHub release exists beside it. The tag is what installs
  and the bundle's pins name; a tag without its release is a different, visible fault.
- Stopping the text that caused #484. That's the guard's job (troupe-run/infrastructure#364).

## Decisions

### D1. The script compares; the workflow lists the tags

`scripts/release_tags.py` reads the config and the manifest from the checkout, and the repository's tag refs
(`refs/tags/<name>`, one per line) from standard input. It prints each missing tag and the repair pointer, and
exits 1 when any is missing. The workflow step lists the refs with
`gh api --paginate repos/<repo>/git/matching-refs/tags --jq '.[].ref'` and pipes them in.

The script stays a pure function of files and text, so its tests need neither the network nor a git repository with
tags. The API reads the tags as they are now, after release-please made them. A checkout would need its tags fetched
after release-please's job, which `actions/checkout` does, but only with full history or explicit fetching.

*Alternative:* the script calls `git ls-remote` itself. Rejected: that puts the network in the script, and its tests
would need a fake remote.

### D2. Tag names come from the config, and anything unexpected is an error

Each manifest path must have a `packages` entry with a `component`, and the config must set
`include-component-in-tag: true`. Otherwise the script fails, naming the path or the setting, rather than guessing
the tag. A version that isn't `X.Y.Z` is also an error. `0.0.0` is skipped: it's how a new member waits for its first
release (`releasing.md`, "Adding a package").

### D3. Its own job, after release-please, even when release-please failed

A new job, `release-tags`, has `needs: release-please` and `if: ${{ !cancelled() }}`, like `notify-website`. It runs
on every push, not only after a release, because a gap stays a gap until it's repaired. Its only permission is
`contents: read` with `GITHUB_TOKEN`. It isn't in the `release` environment, so it never sees the release App's key.
It checks out `main` as it is after release-please, as `pin-bundle` does, so the manifest it reads includes this
run's release.

*Alternative:* a step at the end of the `release-please` job. Rejected: a failed release-please step would skip it,
which is exactly the case it should catch, and the job runs with the App's key in its environment.

### D4. The failure points at the repair

The output names each missing tag, then the release guide's section ("Repairing a missing release" in
`contributing/releasing.md`). That section describes two routes:

1. Edit the merged release pull request's body down to the missing components' blocks. Escape any text that the
   round trip would read as HTML twice more (`&amp;amp;lt;`), relabel it `autorelease: pending`, and re-run the
   release run.
2. As a fallback, `gh release create <tag> --target <merge commit> --prerelease` with the changelog section as the
   notes.

Route 1 was proved locally with release-please 17.6.0 for #263.

## Risks / Trade-offs

- [Every push to `main` fails until the 0.2.0 gap is repaired] → The repair runs before this merges, so this change's
  own merge run passes. If it doesn't, the red run is the check working.
- [A GitHub API failure listing the tags] → `gh api` exits non-zero, the step fails, and its output says why. That's
  a red run with a visible cause, not a silent pass. `--paginate` reads more than one page of tags.
- [A config the script can't read the tags from, such as a component without a `component`] → D2 refuses rather than
  passing, and the error names the path.
