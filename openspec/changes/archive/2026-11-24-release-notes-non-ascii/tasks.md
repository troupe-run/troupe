# Tasks

## 1. Fixtures from the 0.2.0 run

- [x] 1.1 Save eeab95c's `release-notes.md` blob from the git blob API, with each lone `0xA0` put back as ⚠, as
  `scripts/tests/fixtures/release-notes/release-notes-eeab95c-before.md` (text, so the review can read it; the first
  push's `.bin` failed its coverage gate). Verify: encoding it with Node's `'binary'` gives 69,972 bytes with eight
  lone `0xA0` bytes and eeab95c's git blob id.
- [x] 1.2 Save the six affected releases' bodies as published (`<tag>.md`, from `gh release view --json body`).
  Verify: the five hold one U+FFFD each, and troupe-v0.2.0 holds eight and is 69,195 characters long.

## 2. The check

- [x] 2.1 Write the tests first in `scripts/tests/test_release_notes.py`, one per scenario of both requirements
  (design D2 to D6), plus D7's two reproduction tests. Verify: they fail because `release_notes.py` doesn't exist yet. (Done alongside the script instead, so five mutations of it stood in for the fail-first run; the tests caught each one.)
- [x] 2.2 Write `scripts/release_notes.py` (standard library only): read the releases from standard input, take the
  expected tags from `release_tags.expected()`, extract and compare the sections, report, and add `--section <tag>`.
  Verify: `uv run pytest scripts/tests/test_release_notes.py` passes.
- [x] 2.3 Run it against today's real releases:
  `gh api --paginate repos/troupe-run/troupe/releases --jq '.[] | [.tag_name, .body, .draft] | @json' | python3 scripts/release_notes.py`.
  Verify: it exits 1 naming exactly the six releases #486 lists. Also verify that `--section` output for each of the
  six, compared with the repair files in `resume/263-release-repair/fixed/`, differs at most in the heading's date.

## 3. The workflow and the guide

- [x] 3.1 Add the `release-notes` job to `.github/workflows/release.yml` (D5), and tests for it in
  `test_release_workflow.py` beside the tag check's: it runs after release-please even when that failed, reads with
  `GITHUB_TOKEN` outside the release environment, checks out main without credentials, and pipes the releases into
  the script. Verify: those tests pass, and `actionlint` passes if it's available locally (it isn't, so the guard's workflow check in CI covers it).
- [x] 3.2 Add "Repairing a release's notes" to `contributing/releasing.md` (cause, D6's commands, owner-only), and
  point to it from "When something goes wrong". Verify: the link anchor renders (check-rendered-markdown-anchors).

## 4. The Node reproduction and the full check

- [x] 4.1 Run release-please 17.6.0's own code under Node on the 0.2.0 artefacts: encode with `'binary'`, decode the
  blob as UTF-8, parse, write back, parse. Verify: it gives the six published bodies byte for byte. Post the script
  and its output on #486.
- [x] 4.2 `uv run scripts/check.py`, output kept in a scratch file. Verify: it passes.

## Workflow follow-up

- Draft PR closing #486; act on the review; mark ready; archive before merge (`quality_gates.py size` after).
- The six releases: the owner edited them on 2026-11-24, before the merge, and the check exits 0 against all 25 live
  releases. After the merge, check main's next `release-notes` job.
