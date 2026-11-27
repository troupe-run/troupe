# Proposal

## Why

The nightly mutation run (troupe-run/infrastructure run 45823844707) scored three core modules at 0%, under the 60%
threshold, with every mutant reached by no test in the test process: `troupe.core.config.syncing` (#527, 886
mutants), `troupe.core.runners.conformance` (#528, 415) and `troupe.core.runs.changes` (#529, 542). Each is tested
only by integration tests: syncing and changes against a git theatre, conformance by starting a real runner. mutmut
can't see either, so a change to what a sync records, which check a conformance run fails, or what accepting a run's
changes refuses could go unnoticed by the unit tests.

## What Changes

- New unit tests under `packages/troupe/tests/unit`, one module at a time, that run each module in-process and
  reach no process, socket or git theatre (the kinds detector checks every one):
  - `troupe.core.config.syncing`: `sync_config` over a theatre with the `files` version control (no git), for a
    sync with nothing to do, hand edits swept and recorded, a command's own change, both together, a rename,
    rehearsals, `config get`'s record-only sync, conflicts (refused, resolved by a hand edit, left unrecorded by
    `config get`), and the notices each reports (`config.hand-edit-recorded`, `config.hand-move-recorded`,
    `config.conflict-resolved`, `config.hand-edit-unrecorded`), plus `file_notices`.
  - `troupe.core.runners.conformance`: `check_runner` with `troupe.platform.processes.start` replaced by a
    stand-in child whose input and output are in-process streams answered by a scripted runner, and `run_actor`
    replaced by a stand-in outcome. Each check passes against a runner that keeps the contract and fails, with its
    problem, against one that breaks it the way the check looks for; the credential is masked in every problem.
    Nothing is started and no signal is sent: the stand-in's `kill_tree` only records that it was called.
  - `troupe.core.runs.changes`: `diff`, `accept` and `discard` over a `files` theatre's event store with recorded
    runs, a stand-in version control for applying a diff and removing a worktree, and an in-memory artifact store:
    each refusal (not a worktree run, not ended, settled, waiting at a gate, no changes, uncaptured, a conflict),
    a diff in UTF-8 and base64, a rehearsal, what accepting and discarding record, and the notice when a worktree
    can't be removed.
- No source change: the tests pin what the code does today. A defect a test finds is raised as its own issue.
- Not `core/runs/perform.py` or the CLI's waiting hint, which troupe#536 is changing.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. Only tests change; no behaviour does (`skip_specs: true`).

## Impact

New unit test files under `packages/troupe/tests/unit/`, each under the size gate's warning, and any helper they
share beside the suites in `packages/troupe/tests/`. The three modules' mutation scores rise over 60%. syncing and
changes are measured locally with mutmut 3.8.1 on the unit tests only; conformance manages processes, so it isn't
mutated on the host (owner's rule): it's measured in a throwaway container or left to CI's mutation report. Closes
#527, #528 and #529.
