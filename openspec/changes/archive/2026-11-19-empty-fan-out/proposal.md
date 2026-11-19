# Proposal

## Why

`test_a_copy_that_differs_from_a_fresh_build_where_git_looks_compares_unequal[_make_an_empty_fan_out]` fails about
one run in 256 (#442; it dropped #464 from the merge queue). Its helper `_make_an_empty_fan_out` assumes no loose
object in the copied theatre is named `00...`, but the commit's name changes with its time on every run, so sometimes
`objects/00/` already holds it and the helper's assertion fails.

## What Changes

- `_make_an_empty_fan_out` makes an empty fan-out directory under the first two-hex-digit prefix (`00` to `ff`) that
  no directory in the copy's `objects/` uses, rather than assuming `00` is free. What the test proves is unchanged:
  an empty fan-out directory makes the copy compare unequal with a fresh build.
- A new test writes the same real blob whose name starts with `00` into both the copy and a fresh build, checks they
  still compare equal, then applies the helper and checks they compare unequal. It fails on the old helper every
  time, and needs no chance to do so.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. No spec describes the test theatres' comparison, so the change declares `skip_specs`.

## Impact

Tests only: `packages/troupe/tests/test_theatres.py`. No runtime code changes, so no release. Not part of the 0.2.0
milestone: that milestone holds the planned "Other runners" work, and a test fix needs no milestone.
