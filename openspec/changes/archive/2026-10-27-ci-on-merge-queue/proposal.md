# Proposal: CI's check runs on merge queue commits

## Why

troupe-run/infrastructure#169 puts a merge queue in front of `main` in every governed repository (#180). The queue
tests each pull request on top of `main` and whatever is queued ahead of it, and lands only when every required check
reports on the commit it tested. troupe requires `check`, `guard (workflow rules)` and `DCO`. The guard and DCO
already report on merge groups. `check` doesn't: `.github/workflows/ci.yml` runs on `pull_request` and on `push` to
`main` only, so a queue turned on today would wait on `check` until it timed out, and never land anything.

## What Changes

- **`ci.yml` runs on `merge_group`.** A merge group commit is a tree no pull request has tested as a whole, the same
  reason `main` runs everything after a merge (ci-check-scope D5). So a merge group runs the full check on every leg,
  as a push to `main` does, and reports the same one `check`.
- **Nothing narrows a merge group.** The `changes` job already runs only on `pull_request`, so on a merge group it's
  skipped, the legs get no answer, and no answer means the full check. `scripts/check_result.py` already passes
  `check` when every leg passed. No script changes.
- **A test keeps it that way.** A new test reads `ci.yml` and fails when `merge_group` is missing from its triggers,
  when any trigger gains a path filter, or when the `changes` job can run on anything but `pull_request`. The
  workflow's header comment says why, so a later path filter or a widened `changes` can't quietly skip a required
  check on the queue.
- **`pyyaml` becomes a declared dev dependency**, with its type stubs, for that test. It's in the lock today only
  through `datamodel-code-generator` (design D2).

Out of scope:

- **Turning troupe's queue on.** That's troupe-run/infrastructure's ruleset, applied only after this merges. Until
  then nothing sends `merge_group`, so the new trigger is harmless.
- **`guard` and DCO.** The guard workflow is delivered from troupe-run/infrastructure and already runs on
  `merge_group`. DCO already reports on merge groups (infrastructure's probe).
- **Narrowing the check on the queue.** A merge group runs everything, like `main`. Whether the push to `main` after
  a queue merge still needs its own run is infrastructure's question, not this change's: this change keeps it.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `quality-check`: the requirement that every push to `main` runs the full check covers every merge group too, and
  the one required `check` reports on merge groups as well as pull requests and pushes to `main`.

## Impact

- `.github/workflows/ci.yml`: `merge_group:` in `on`, and the header comment.
- `scripts/tests/test_ci_workflow.py`: new, in the `scripts` scope.
- `pyproject.toml` and `uv.lock`: `pyyaml` and `types-PyYAML` in the dev group.
- troupe-run/infrastructure#169: unblocks turning on troupe's queue. Comment there when this merges.
