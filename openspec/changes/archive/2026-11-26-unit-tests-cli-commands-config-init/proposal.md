# Proposal

## Why

The nightly mutation run (troupe-run/infrastructure run 45621303078) put three CLI command modules far under the 60%
threshold: `troupe.cli.init` at 0% (#519: all 423 mutants reached by no unit test), `troupe.cli.config` at 5.9%
(#518: 167 survived, 640 unreached) and `troupe.cli.commands` at 1.9% (#517: 189 survived, 486 unreached). Every
command these modules run calls the core, and the core needs a git theatre, so the commands are tested only by
integration tests that run troupe in a child process or against a git theatre, which mutmut can't see. A change to
the request a command sends, the text it prints or the exit code it returns could go unnoticed by the unit tests.

## What Changes

- New unit tests under `packages/troupe/tests/unit` that run each command in-process through `troupe.cli.main([...])`,
  with the core's handlers replaced by stand-ins through the dispatcher's own `methods` argument. The real dispatcher
  still parses each request strictly with the protocol's request class, and each stand-in's result and updates are
  the protocol's message classes, so every request checked and result rendered is a shape troupe really sends.
- The tests assert what a person sees and what the core is asked: the request's params, standard output and
  standard error line for line, and the exit code, for the cases the survivors show unchecked:
  - `troupe.cli.init`: the `--runner` without `--audition` refusal, the request (audition, runner, rehearse), the
    made and rehearsed theatre with and without an example actor, each step's commands and notes (commit, allow the
    local stage, perform with each runner, the runtime key's variable and its override, the token budget, the extra
    to install), and notices.
  - `troupe.cli.config`: `config set`, `unset` and `mv` (their requests, each entry's and file's line, hand edits
    recorded, nothing changed, rehearsals, the recorded change), the `path=value` refusal, the runner a value is
    typed for, `config get` (a value, a string, nothing set, empty config, conflicts with long values shortened,
    `--resolved`, `--json`), `sync`, `config drop` and `config keep`.
  - `troupe.cli.commands`: `perform` (started and worktree lines, events, notices, a rehearsal's lines, each
    outcome's text and exit code, the settle hint for each worktree state, and Ctrl-C asking the core to cancel),
    `status`, `logs` (followed entries not repeated, the run's line, actor and audit, `--json`, a cancelled follow),
    `diff` (UTF-8, base64, nothing changed, `--json`), `accept` and `discard`.
- One shared helper beside the suites, `tests/cli_core_stand_in.py`, holds the stand-in core: it records each call's
  method, request and session, sends the updates it's given and returns the result it's given.
- No source change: the tests pin what the code does today. If a test finds a defect, it's raised as its own issue.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. Only tests change; no behaviour does (`skip_specs: true`).

## Impact

New unit test files under `packages/troupe/tests/unit/` (one or more per module, each under the size gate's warning)
and the helper `packages/troupe/tests/cli_core_stand_in.py`. Mutation scores of `troupe.cli.init`,
`troupe.cli.config` and `troupe.cli.commands` rise over 60%, measured locally with mutmut 3.8.1 on the unit tests
only, with CI's settings. CI's mutation report can't confirm a tests-only change (it mutates only changed source
files), so the local scores and the survivors left are recorded in the pull request, and the next nightly run
confirms them. Closes #517, #518 and #519.
