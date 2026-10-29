# Design

## Context

See proposal.md, "Why". `scripts/tests/workspace/test_release_config.py` builds a `copy` fixture from the real
repository's files, breaks one property, and compares `release_config.problems(copy)` with an exact list of messages.
Three of the expected messages embed the protocol's manifest version, which `release_config._record_problems` reads
from the copy's `.release-please-manifest.json`. The tests write that version as the literal `0.0.0`.

Other `0.0.0` literals in the file are not version assumptions and stay: the fix `release_config` suggests for a
member or protocol missing from the manifest is the constant `0.0.0` (proposal, "Impact"), and the `0.0.0` inside
the bad record contents (`'["0.0.0"]'`, `'{"version": "0.0.0", "extra": 1}'`) is just content that's malformed
whatever the version.

## Goals / Non-Goals

**Goals:**
- Every test in the file passes on main and on a release pull request, whatever versions the manifest holds.
- A test that assumes a version fails in the ordinary check on main, not first on a release pull request.

**Non-Goals:**
- Changing `release_config.py` or the messages it returns.
- Simulating everything a release pull request changes (changelogs, `pyproject.toml` and `uv.lock` versions).
  `release_config.problems` doesn't compare those versions, so bumping them in the copy would test nothing.

## Decisions

### D1. The tests read the protocol's version from the copy

A helper, `released(copy)`, returns `json.loads((copy / MANIFEST).read_text())["protocol"]`, and the three tests
build their expected messages from it. This is the same source `release_config` reads, which is the point: the
tests check that the message names *the manifest's* version, so they must take it from the manifest.

*Alternative:* pin the copy's manifest and record to a fixed version (for example, set both to `0.0.0` in the
fixture). Rejected: the copy would no longer be the real files, which the fixture's docstring promises, and
`test_the_copy_of_the_real_files_has_no_problems` would stop checking the real manifest against the real record.

### D2. The "different" version is derived, and can't equal the manifest's

`test_a_record_that_differs_from_the_manifest_names_both_files_and_versions` writes the next major version after the
manifest's (`0.1.0` → `1.0.0`). It is built from the manifest's version, so it differs from it by construction, and
it is still a valid version, so the test checks a real difference rather than a malformed record. The test asserts
the two differ before using it, so a mistake in the derivation fails loudly rather than testing nothing.

*Alternative:* a far-off literal such as `99.0.0`. Rejected: it's the same assumption as `0.2.0`, just further away.

### D3. Every fixture-based test runs on the repository as is and as a release leaves it

The `copy` fixture is parametrized with two ids:

- `as-is`: the real files, unchanged (today's behaviour).
- `released`: the same, then every version in the copy's manifest bumped to its next minor (`0.0.0` → `0.1.0`), and
  the recorded protocol version set to the bumped protocol version, as a release pull request releasing everything
  would leave them (pre-1.0 `feat`: next minor, per the releases spec's "Pre-1.0 versioning").

So the whole file, including tests added later, runs against a manifest whose versions aren't the ones on main. The
`released` copy is consistent, so `test_the_copy_of_the_real_files_has_no_problems` must pass on it too, which checks
that the bump in the fixture really is the state a release leaves.

*Alternative:* add `released` cases only to the three affected tests. Rejected: that fixes these six failures but
not the class of mistake. A new test that hard-codes a version would pass on main and fail first on the next release
pull request, as these did.

`test_every_workspace_member_is_configured_for_release` runs on the real repository rather than a copy, and stays as
it is.

## Risks / Trade-offs

- [The file's test count roughly doubles] → each case copies about a dozen small files into `tmp_path`; the file
  runs well under a second today, and the added cost is in the same range.
- [The `released` bump drifts from what release-please actually writes] → it is checked against the real thing
  once, in this change: the fixed tests are run on the files from the release pull request's branch (tasks), where
  the manifest and record hold what release-please wrote.
