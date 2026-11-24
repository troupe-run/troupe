# Proposal

## Why

When a release pull request's body is too large (65,536 characters), release-please 17.6.0 saves it to
`release-notes.md` on a side branch with `Buffer.from(notes, 'binary')`, which keeps only the low byte of each
character. After the merge it reads that file back as UTF-8, so every character above U+00FF comes out as U+FFFD. In
0.2.0 that turned `### ⚠ BREAKING CHANGES` into `### � BREAKING CHANGES` in six published releases, and the run
passed (#486, follow-up to #484). Nothing compares what was published with the changelog it came from. That gap
also hid #484's other casualty: troupe-v0.2.0's notes swallowed seven later components' blocks. 0.3.0's release pull
request (#491) has breaking changes too, so the check has to land before it merges.

## What Changes

- After every release run on `main`, a new `release-notes` job compares each manifest version's GitHub release notes
  with that version's section of the component's `CHANGELOG.md`. The heading's date may differ, since the changelog is
  dated when the release pull request was written and the notes when it merged. Any other difference fails the run,
  naming each release, the first line that differs, and how many U+FFFD characters the notes hold.
- The release guide gets a "Repairing a release's notes" section. A new `--section <tag>` mode of the script prints
  the changelog section to publish with `gh release edit`. Only the owner runs that command.
- A test reproduces the 0.2.0 case from eeab95c's saved notes, the raw git blob as release-please read it. Decoding
  it as release-please does gives U+FFFD in place of every ⚠. The releases built from it, and the six releases as
  published, fail the check naming exactly the affected components. The 19 releases published correctly pass it.
- Not changed: the six published releases. The owner holds their corrected notes and decides whether to edit them
  (#486). Until they're edited, the check fails on every push, the same way `release-tags` treats a missing tag.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `releases`: adds "Every release's notes match its changelog section", a check after each release run. It sits
  beside "Every recorded version has its release tag".

## Impact

- `scripts/release_notes.py` (new, standard library only, like `release_tags.py`), and its tests in
  `scripts/tests/test_release_notes.py`, with fixtures under `scripts/tests/fixtures/release-notes/`.
- `.github/workflows/release.yml`: a new `release-notes` job, read-only with `GITHUB_TOKEN`, and its tests in
  `scripts/tests/test_release_workflow.py`.
- `contributing/releasing.md`: the repair section, and a pointer from "When something goes wrong".
- The full release-please reproduction (write, read back, parse, write back, parse) needs release-please's Node code,
  which troupe's tests don't run. It's recorded on #486 with the script and its output.
