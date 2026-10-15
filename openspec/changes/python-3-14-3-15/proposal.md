# Proposal

## Why

#104 asks troupe to support and test Python 3.14 and 3.15, which developers already have installed. The #100 flake
hunt ran on 3.15. Part 1 (#105, landed in #106) capped the bound at the versions CI tests, `>=3.12,<3.14`. This
change is Part 2, tracked as #107: it adds 3.14 and 3.15 to CI and widens the bound to match.
troupe-run/infrastructure#43 waits on it, because those CI jobs have to exist before they can be made required.

## What Changes

- **CI matrix:** `.github/workflows/ci.yml` tests `["3.12", "3.13", "3.14", "3.15"]` on Linux, macOS and Windows,
  which is 12 jobs instead of 6.
- **Bound:** `requires-python = ">=3.12,<3.16"` in all nine `pyproject.toml` files, and `uv.lock` re-locked. Part
  1's check refuses the bound and the matrix moving separately, so they change together.
- **One real 3.14 failure, fixed in a test helper.** It was found by running the full check on 3.14 and 3.15 in a
  widened copy of the repository on macOS. The suite passes apart from
  `test_a_kill_sent_after_the_child_exited_but_before_asyncio_saw_it_did_not_end_it`, which fails on both versions.
  From 3.14, asyncio's threaded child watcher waits with `waitid(WNOWAIT)` and reaps the child on the event loop.
  The test's macOS helper assumed the watcher thread reaps, so it waited for a pid that stays a zombie while the
  loop is blocked. troupe's seam is unaffected. The helper changes to use `waitid` wherever `os` has it, as it
  already does on Linux, and keeps the pid probe only where `waitid` is missing (macOS on 3.12).
- **Part 1's script tests stop hard-coding today's bound.** They assumed `>=3.12,<3.14` and 3.15 as the
  unsupported version, so widening broke 19 of them. They now read the bound from the repository, so the next
  version bump needs no test edits.
- **A deprecation warning, silenced deliberately.** 3.14 marks `argparse.FileType` pending deprecation. troupe
  never uses it. `parser.py` refuses it, and one test builds one to prove that. That test now expects the warning on
  3.14 and later, rather than leaving it in every run's output.
- **README:** names 3.12 to 3.15.

Dependencies all resolve. Every runtime dependency has wheels for 3.14 and 3.15 on all three platforms. The one
gap is `grimp` 3.17, which the dev tool import-linter uses: it has no 3.15 wheel for macOS arm64, so the macOS 3.15
jobs build it from source with Rust. It built locally in seconds. If the CI runner can't build it, the proposal is
revisited rather than 3.15 being dropped quietly.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. The `python-support` spec keeps the supported versions out of its requirements and defers them to the
bound. Every scenario that names versions is phrased as "while the bound is ...", so all of them still hold. No
spec-level behaviour changes, so the change sets `skip_specs: true`.

## Impact

- **Files:** `ci.yml`, the nine `pyproject.toml` files, `uv.lock`, `packages/troupe/tests/test_platform_processes.py`,
  `packages/troupe/tests/test_cli.py`, `scripts/tests/test_python_versions.py`, `scripts/tests/test_on.py`, and
  `README.md`.
- **CI:** 12 check jobs instead of 6. That's more runner minutes per PR, and the new ones aren't required until
  infrastructure#43 lists them.
- **Developers:** `uv run scripts/on.py 3.14 ...` and `on.py 3.15` work once this merges. `.python-version` stays
  `3.12`.
- **Issues:** closes #107. #104 then has both sub-issues done.
