# Design

## Context

See proposal.md, "Why". Each step below was checked on 2026-11-24 against release-please 17.6.0's code and
troupe's 0.2.0 run:

- **Write.** `PullRequestOverflowHandler.handleOverflow` saves an overlong body with
  `github-api.js` `createFileOnNewBranch`, which encodes it with `Buffer.from(contents, 'binary')`. Node's `'binary'`
  is latin1, so it keeps each UTF-16 code unit's low byte: ⚠ (U+26A0) is stored as a lone `0xA0`.
- **What git holds.** eeab95c's blob for `release-notes.md` is 69,972 bytes with eight lone `0xA0` bytes
  (`git/blobs/<sha>`). The contents API (`contents/release-notes.md?ref=eeab95c`) re-encodes invalid UTF-8 as latin1
  and returns 69,980 bytes with `c2 a0` (U+00A0). That's why #486 reported U+00A0. It's what the contents API shows,
  not what release-please read.
- **Read.** `parseOverflow` reads the file through `@google-automations/git-file-utils`, from the blob, with
  `Buffer.from(content, 'base64').toString('utf8')`. A lone `0xA0` decodes to U+FFFD, which is in every affected
  published release.
- **Changelogs.** These are written to the release pull request's branch through the tree API, encoded as UTF-8, so
  `CHANGELOG.md` keeps its ⚠. The changelog is the copy that survived.

The published releases bear this out. With each heading's `(YYYY-MM-DD)` set aside, 19 of the 25 published releases
equal their changelog sections byte for byte. The other six are the ones #486 names: five differ by one U+FFFD, and
troupe-v0.2.0 is 69,189 characters long against its 23,323-character section.

`scripts/release_tags.py` (release-missing-components) is the pattern this follows. It's a standard-library script
the release workflow pipes GitHub data into, with the config and manifest read through `release_config.py`.

## Goals / Non-Goals

**Goals:**

- A release run that publishes notes different from the changelog fails on the push where it happened, naming each
  release. It fails whatever the cause: lost non-ASCII text, swallowed blocks (#484), or a hand edit gone wrong.
- A test from the real 0.2.0 artefacts shows the check would have caught 0.2.0.

**Non-Goals:**

- Fixing release-please's encoding. The action bundles its own copy, so patching it means forking or replacing the
  action. Reporting it upstream is outward-facing, so it's the owner's call.
- Editing releases automatically. The owner decides what's published (#486's third "Done when"), and an automatic
  edit would put the release App's write token in the job that judges the notes.
- Stopping a body from overflowing. Its size comes from the commits being released.

## Decisions

### D1. The script compares; the workflow lists the releases

`scripts/release_notes.py` reads the config, the manifest and each component's `CHANGELOG.md` from the checkout. It
reads the releases on standard input, one JSON array `[tag, body, draft]` per line. The workflow lists them with
`gh api --paginate repos/<repo>/releases --jq '.[] | [.tag_name, .body, .draft] | @json'`. That's one paginated call
whatever the number of components, and `@json` keeps each body, newlines included, on one line.

*Alternative:* one `gh release view <tag>` per expected tag. Rejected: that's a call for every component, and the
script would have to print its tag list first for the workflow to loop over.

### D2. Equal except the heading's date

Both texts have CRLF turned into LF and surrounding whitespace stripped. Then a trailing ` (YYYY-MM-DD)` is removed
from the first line, and only from the first line. Anything else that differs counts. The changelog's date is when
the release pull request was last written, and the release's is when it merged, so the date is the one difference
expected (#486). Comparing on that rule passes all 19 good 0.2.0-era releases and fails all six bad ones (Context).

The failure names the release, the line number and both versions of the first line that differs, and the count of
U+FFFD characters in the notes, which points straight at this cause.

*Alternative:* only look for U+FFFD in the notes. Rejected: that misses #484's swallowed blocks, and a changelog that
genuinely holds U+FFFD would be a false alarm.

### D3. Every manifest version, every push

As in `release-tags` (release-missing-components D3), the expected tags are `<component>-v<version>` for each
manifest version other than `0.0.0`. The check runs on every push, not just after a release, so bad notes stay a
failure until they're repaired. It reuses `release_tags.expected()` for the tag list, so the two checks can't disagree
on which tags exist.

Consequence: once this merges, main's release run fails until the owner corrects the six 0.2.0-era releases or decides
to leave them. The owner already holds the corrected notes. If the decision is to leave them, D3 changes to only this
run's releases: the step's input and two scenarios change, and the comparison stays the same.

*Alternative:* check only the releases this run created (the action's `paths_released`). Kept as that fallback. It
stops checking a bad release after the run that made it, and it can't catch a release edited by hand later.

### D4. Inputs that don't fit are errors

A tag with no release, or with only a draft, fails as "no notes to compare". A tag listed twice on the input, a line
that isn't a `[string, string, bool]` array, a changelog file that's missing, or a changelog with no section for the
version all fail, naming the input. A tag with no section isn't a pass. Releases on the input that the manifest
doesn't name, such as older versions, are ignored. A section starts at a `## ` heading whose version is
`[X.Y.Z]` or `X.Y.Z`, and runs to the next `## ` heading.

### D5. Its own job, beside `release-tags`

A new job, `release-notes`, has `needs: release-please`, `if: ${{ !cancelled() }}`, `contents: read` and
`GITHUB_TOKEN`, and checks out `main` without credentials, the same as `release-tags`. It's a separate job so that
each failure names its own check in the run summary.

### D6. Repair prints the section; the owner edits

`release_notes.py --section <tag>` prints the changelog section for that tag (the config names the component, the
tag gives the version). The release guide's new "Repairing a release's notes" section gives the owner's command:

```sh
uv run scripts/release_notes.py --section <tag> > notes.md
gh release edit <tag> -R troupe-run/troupe --notes-file notes.md
```

The published heading then carries the changelog's date, which D2 allows.

### D7. The reproduction runs on the real artefacts; the Node round trip is recorded on #486

The fixtures are eeab95c's raw blob (`release-notes-eeab95c.bin`, 69,972 bytes) and the six releases' bodies as
published on 2026-11-24. The tests:

1. **The stored text.** Turning each `### ⚠ BREAKING CHANGES` in the changelogs into Node's latin1 bytes gives the
   exact bytes in the blob. Decoding the blob as UTF-8 with replacement, as git-file-utils does, gives U+FFFD in place
   of every ⚠ and leaves the rest unchanged.
2. **The check catches it.** Each released component's block is taken from the decoded blob and checked against the
   changelogs. The check fails naming troupe, troupe-plugin-sdk, troupe-runner-anthropic,
   troupe-runner-claude-code, troupe-runner-openai and troupe-runner-scripted. The six published bodies fail the
   same way, and their changelog sections pass.

The block split in test 2 is a simple `<details>` split, not release-please's parser. That's enough because the
check, not the parser, is what's under test. The full round trip (write, read, parse, write back, parse) runs
release-please's own code under Node, which troupe's tests don't run. The script and its output go on #486, which
the issue allows.

## Risks / Trade-offs

- [A future release-please writes the changelog and the notes differently] → the check fails, naming the releases,
  and D2's rule gets revisited. A false failure is visible. A silent pass is what this change exists to stop.
- [Release notes edited by hand in GitHub's UI arrive with CRLF] → D2 turns CRLF into LF before comparing.
- [main's release run is red until the six releases are repaired] → D3 says why. Repairing them is one command each,
  and the owner already holds the files.

## Migration Plan

Merge before #491. Then the owner runs the six `gh release edit` commands (or decides to leave the releases, which
switches D3 to its fallback). After #491 merges, its run's `release-notes` job checks 0.3.0's notes. Rollback is
removing the job.
