# Design: theatre-copy-fanout

## Context

`_observed()` in `packages/troupe/tests/test_theatres.py` reduces a repository to what a test can see, minus what
differs between any two builds of it (theatre-template-and-guard-xdist design D3: the commit's time, and so its SHA
and its object's file name). It names each `objects/<xx>` directory `objects/<fan-out> dir` and each loose object
`objects/<fan-out>/<loose object> <mode>`, and counts them. Hiding the names isn't enough: the *number* of fan-out
directories also follows the names, because objects whose names share their first two hex digits share a
directory. See proposal.md for the numbers.

**Does an empty fan-out directory matter to git?** No. Git makes `objects/<xx>` when it first writes a loose object
there, reads an object by opening its path, and treats a missing or empty directory the same as one with no matching
file. `git prune` removes empty ones. No git command a test runs answers differently for one. So the comparison could
leave fan-out directories out entirely. This design still counts the empty ones, because neither a fresh build nor a
copy makes one, and one turning up would mean the copy step (or git under it) does something nobody expects.

## Goals / Non-Goals

**Goals:**

- The comparison gives the same answer for any two builds of a shape, whatever their commits' names.
- It still fails a copy that's missing a loose object or a ref, or holds an empty fan-out directory.
- The new test fails on today's comparison deterministically, not 3 times in 100.

**Non-Goals:**

- Changing how copies are made (`gitrepo.from_template`) or the template shapes. The copy has no defect here.
- Comparing objects by name. The commit's name differs by construction, and the trees' and blobs' are already
  checked through `for-each-ref`'s `%(tree)`, `ls-files -s` and `status`.

## Decisions

### D1. Count loose objects and empty fan-out directories, not fan-out directories

In `_observed()`, a loose object keeps its entry (`objects/<fan-out>/<loose object> <mode>`, counted). A fan-out
directory is counted only when it holds nothing, as `objects/<fan-out> empty dir`. Every other path under `.git` is
named and counted as now.

*Alternatives:*

- Leave fan-out directories out entirely. Rejected: an empty one costs nothing to count, and it's the thing #408
  first suspected. If one ever appears, the test should say so.
- Make every build's commit name the same by pinning the commit time in `build_committed()`. Rejected: it hides the
  difference by making it impossible, and it changes every test that uses `committed()` (D3's audit was done for
  real commit times, and a test comparing SHAs across theatres would quietly start passing for the wrong reason).

### D2. The test that fails first builds both layouts on purpose

The new test builds `committed()`'s theatre from scratch twice, with commit times fixed through `gitrepo.AUTHOR`
(monkeypatched with `GIT_AUTHOR_DATE` and `GIT_COMMITTER_DATE`, which `Repo.git` reads at call time). The times are
1700000030 (the commit lands in `56/`, shared with a fixed object: 4 directories) and 1700000000 (in `c2/`, its own:
5 directories), found by building at successive times. The test first asserts the premise, that the two `.git/objects`
directories hold different numbers of fan-out directories and the same number of loose objects, so a change to
`committed()`'s contents that broke the collision would fail the test loudly instead of making it pass vacuously.
Then it asserts `_observed()` is equal for the two. On today's comparison that last assertion fails, every run.

Its name says what it checks: two builds whose commits fall into different fan-out directories look the same.

### D3. Strictness kept, by tests that alter one copy

Three tests take a copy and a fresh build of `committed()` and change one thing in the copy, each of which must make
`_observed()` unequal:

- a loose object's file removed (a blob's, whose name is fixed, so the test knows which one);
- `refs/heads/main` removed;
- an empty `objects/00` directory made (`00` is not a fixed object's prefix, and the commit's is checked not to be).

The existing `[committed]`, `[make_repo-files]` and `[make_repo-reftable]` cases stay as they are.

## Risks / Trade-offs

- **The fixed times stop producing the two layouts** (`committed()`'s files, the author, or git's commit format
  change) → D2's premise check fails, naming the counts, and new times are found the same way.
- **An empty fan-out directory appears in a fresh build on some git** (none does today) → the comparison still
  matches, as long as copy and build agree. If only one side has it, the test fails, and the D1 alternative (leave
  fan-out directories out) is the fallback, since git ignores them.
