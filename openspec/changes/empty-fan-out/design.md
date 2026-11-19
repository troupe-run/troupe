# Design

## Context

See proposal.md, Why. `_observed` leaves out non-empty fan-out directories (how many there are follows the objects'
names) and counts empty ones, which no build makes (troupe#408). So the alteration only needs *some* fan-out
directory to exist and be empty in the copy.

## Goals / Non-Goals

**Goals:**
- The helper makes an empty fan-out directory whatever the copy's objects are named.
- A deterministic test shows the old helper's failure and the new helper's fix.

**Non-Goals:**
- Changing `_observed` or the theatres themselves.

## Decisions

### D1. Pick the first prefix the copy's `objects/` doesn't use

The helper walks `f"{n:02x}"` for `n` in `0..255` and makes the first that doesn't exist in `objects/`. It asserts
one was found (a committed() theatre has six loose objects, so 250 or more are always free). The first free one,
not a random one, keeps a run reproducible from the copy's layout.

The prefix only needs to be free in the copy. If the fresh build has objects under it, that directory is non-empty
there and left out of `_observed`, while the copy's is empty and counted, so the two still compare unequal for the
reason the case is about.

### D2. The deterministic test uses a real `00...` blob, in both repositories

The test finds content whose blob name starts with `00` by hashing `b"blob <len>\0" + content` with SHA-1 for
`content = str(i)` until one matches (deterministic, a few hundred hashes), and writes it into each repository with
`git hash-object -w` from a file outside the worktree, so status is unaffected. Writing it into both keeps them equal
before the alteration (asserted as the premise), so the inequality afterwards comes from the empty fan-out alone. A
real object, rather than a patched listing, is what CI met.

Against the old helper the test fails at the helper's `assert not (git_dir / "objects" / "00").exists()`. That run is
recorded in tasks 1.1.

## Risks / Trade-offs

- If committed() changes so a repository has a `00` object of its own, the premise still holds: both have the same
  layout, since `00/` holds objects in both.
