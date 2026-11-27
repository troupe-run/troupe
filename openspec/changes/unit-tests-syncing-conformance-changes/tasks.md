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

- [ ] 2.1 Add unit tests for `check_runner` with stand-ins for `processes.start` and `run_actor` (design D3): every
  check passing against a runner that keeps the contract, each failing with its problem against one that breaks it,
  a timeout, an `OSError`, the whole run's outcome, and the credential masked. Verify they pass, start nothing and
  send no signal (the kinds detector passes them); commit
- [ ] 2.2 Measure conformance's score off the host (design D5): in a throwaway container, or from CI's mutation
  report or the next nightly run. Record it

## 3. troupe.core.runs.changes (#529)

- [ ] 3.1 Add unit tests for `diff`, `accept` and `discard` over a `files` theatre with recorded runs, a stand-in
  version control and an in-memory artifact store (design D1, D2): each refusal, UTF-8 and base64 diffs, a
  rehearsal, what accepting and discarding record, and the worktree-not-removed notice. Verify they pass
- [ ] 3.2 With the local mutation slot granted, run mutmut on the unit tests, scoped to `troupe.core.runs.changes`.
  Verify it scores over 60%; record the score and survivors; commit

## 4. Checks

- [ ] 4.1 `uv run scripts/check.py` passes before each commit
- [ ] 4.2 With the slot granted, run syncing's and changes' mutmut once more on every test of this change; record
  each score and the survivors left, with why each is equivalent or out of reach, here and in the PR

## Workflow follow-up

- Draft PR closing #527, #528 and #529, with the scores and survivors in its body; act on the review; archive on
  the branch before merge.
