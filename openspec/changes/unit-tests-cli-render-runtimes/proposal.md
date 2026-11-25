# Proposal

## Why

The nightly mutation run (troupe-run/infrastructure run 45621303078) put two CLI text modules under the 60% threshold:
`troupe.cli.render` at 51.1% (#520: 257 survived, 112 reached by no unit test) and `troupe.cli.runtimes` at 0% (#521:
all 110 mutants reached by no unit test). Both modules only format structured data as text, and much of that text is
checked only by integration tests that run troupe in a child process, which mutmut can't see. So a change to what
`troupe logs`, `troupe status`, `config get --resolved` or a rehearsed `perform` prints could go unnoticed by the unit
tests.

## What Changes

- New unit tests under `packages/troupe/tests/unit` that call the module's functions in-process and assert the exact
  text they produce, for the cases the survivors show unchecked:
  - `troupe.cli.render`: each run event type's line (`init`, `turn`, `tool_call`, `tool_result`, `retry`, `context`,
    `log`, `oversized`), the first-line cut at 100 characters, `context` events' counts, an error's and a notice's
    text with and without a path, a recorded notice's line, a run's summary (actor renamed, runner reported, workspace,
    error, audit, transcript, stderr, recording failure, worktree changes, notices), and a run's list line.
  - `troupe.cli.runtimes`: a resolved runtime's lines (endpoint or in-process, model or how to set one, credential
    named directly or by a variable, set or not, engine, price) and the price's wording.
- Existing tests in `test_cli_render.py` stay as they are. The event, notice and error lines are added beside them;
  the run summary's lines go in a new `test_cli_render_summary.py`, which keeps both files under the size gate's
  warning, and the runtimes tests in a new `test_cli_runtimes.py`.
- Every fixture is first read by the protocol's own message class (`ResolvedRuntime`, `LoggedEvent`, `LoggedNotice`,
  `RunSummary`), so the text pinned is that of a shape troupe really sends.
- No source change: the tests pin what the code prints today. If a test finds a defect, it's raised as its own issue.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. Only tests change; no behaviour does (`skip_specs: true`).

## Impact

`packages/troupe/tests/unit/test_cli_render.py` (extended), and `test_cli_render_summary.py` and
`test_cli_runtimes.py` (new) beside it. Mutation scores of `troupe.cli.render` and `troupe.cli.runtimes` rise over
60%, measured locally with mutmut 3.8.1 on the unit tests only, with CI's settings, and confirmed by the PR's
mutation report. Closes #520 and #521.
