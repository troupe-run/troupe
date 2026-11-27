# Tasks

## 1. troupe.core.config.syncing (#527)

- [x] 1.1 Add unit tests for `sync_config` over a `files` theatre (design D1, D2): nothing to do, hand edits
  recorded (and a file removed), a command's own change, both, a rename and a rename already moved by hand,
  rehearsals, `config get`'s record-only sync, conflicts refused, resolved by a hand edit and left unrecorded, and
  each notice's text and details; and `file_notices`. Verify the files pass and the kinds detector passes them
- [x] 1.2 With the local mutation slot granted, run mutmut on the unit tests, scoped to `troupe.core.config.syncing`
  (design D5). Verify it scores over 60%; kill what's worth killing; record the score and the survivors left, with
  why; commit. Measured 2026-11-27 (1 child, the memory cap nulled in the clone only): 770 of 886 caught (86.9%),
  before the tests of the actor given, the lock, the sweep's change after a merge, a non-ASCII value, every file and
  value an edit leaves, and force (aimed at about 40 of the 116 left; task 4.2 measures them)

## 2. troupe.core.runners.conformance (#528)

- [x] 2.1 Add unit tests for `check_runner` with stand-ins for `processes.start` and `run_actor` (design D3): every
  check passing against a runner that keeps the contract, each failing with its problem against one that breaks it,
  a timeout, an `OSError`, the whole run's outcome, and the credential masked. Verify they pass, start nothing and
  send no signal (the kinds detector passes them); commit. 34 tests, every line and branch of conformance.py run
- [x] 2.2 Measure conformance's score off the host (design D5): in a throwaway container, or from CI's mutation
  report or the next nightly run. Record it. Measured 2026-11-27 in a throwaway `python:3.12-bookworm` container
  (only the clone mounted, unit tests only, 1 child, the 2048 MB memory cap on): 404 of 415 caught (97.3%), before
  the test of the cancel's run id and the check of each verdict's type (aimed at 3 of the 11 left, not measured)

## 3. troupe.core.runs.changes (#529)

- [x] 3.1 Add unit tests for `diff`, `accept` and `discard` over a `files` theatre with recorded runs, a stand-in
  version control and an in-memory artifact store (design D1, D2): each refusal, UTF-8 and base64 diffs, a
  rehearsal, what accepting and discarding record, and the worktree-not-removed notice. Verify they pass
- [x] 3.2 With the local mutation slot granted, run mutmut on the unit tests, scoped to `troupe.core.runs.changes`.
  Verify it scores over 60%; record the score and survivors; commit. Measured 2026-11-27 (1 child, the memory cap
  nulled in the clone only): 576 of 609 caught (94.6%), before the tests of the stores each command opens for its
  session, the settle lock's name and a second settling, a diff file already gone, a gate's keep, and a waiting
  run applying nothing (aimed at about 15 of the 33 left; task 4.2 measures them)

## 4. Checks

- [x] 4.1 `uv run scripts/check.py` passes before each commit
- [x] 4.2 With the slot granted, run syncing's and changes' mutmut once more on every test of this change; record
  each score and the survivors left, with why each is equivalent or out of reach, here and in the PR. Measured
  2026-11-27 (1 child, the cap nulled in the clone only): `troupe.core.config.syncing` 781 of 886 caught (88.1%),
  and 787 (88.8%) with the six mutants the last syncing asserts kill, each checked through mutmut's trampoline;
  `troupe.core.runs.changes` 595 of 609 (97.7%), and 596 (97.9%) with the conflict naming two files. The survivors
  left, and why, are in the PR's body

## Workflow follow-up

- Draft PR closing #527, #528 and #529, with the scores and survivors in its body; act on the review; archive on
  the branch before merge.
