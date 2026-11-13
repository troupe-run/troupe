# Proposal

## Why

`test_theatres.py::test_a_copy_shows_git_what_a_fresh_build_of_its_shape_shows[committed]` fails in about 3 runs in
100, on any OS (troupe-run/troupe#408, first seen on Windows/3.13 in run 43356203947: 5 `objects/<xx>` directories
in the copy, 4 in the fresh build, 6 loose objects in each). Nothing leaves an empty directory behind. The comparison
counts fan-out directories, and how many there are depends on the commit's SHA, which depends on when the commit was
made. The copy's commit was made when the template was built and the fresh build's commit a moment later, so they
differ, as theatre-template-and-guard-xdist design D3 already says they do.

`committed()`'s other five objects (three blobs and two trees, with fixed SHAs) sit in four fan-out directories: `56`
(two objects), `87`, `99` and `af`. A commit whose name starts with one of those four adds no directory. That's
4 in 256 commit times, so a copy and a fresh build differ in their directory count about 3% of the time when exactly
one of them collides. Two fresh builds show it with no copy at all: commit times 1700000000 and 1700000030 give 5 and
4 directories, with 6 loose objects each.

## What Changes

- The comparison in `test_theatres.py` stops counting fan-out directories, since their number follows object names
  that differ between any two builds. It counts what can't differ: loose objects (with their modes), and fan-out
  directories that hold no object.
- A test that fails on today's code: two fresh `committed()` builds, with commit times chosen so that one commit
  shares a fan-out directory with a fixed object and the other doesn't, look the same to the comparison. The test
  checks its own premise (the two directory counts differ), so it can't pass by building two identical layouts.
- Tests that the comparison is still strict about what matters: a copy missing a loose object, missing a ref, or
  holding an empty fan-out directory compares unequal to a fresh build.
- No change to how a copy is made (`gitrepo.from_template`). The copy carries no empty directory; there's nothing in it
  to fix.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. This changes a test's comparison and adds tests. No requirement in `openspec/specs/` describes theatre copies,
so the change sets `skip_specs: true`.

## Impact

- `packages/troupe/tests/test_theatres.py` only.
- Closes troupe-run/troupe#408.
