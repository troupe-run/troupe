# Design

## Context

See proposal.md for why. Every command in `troupe.cli.init`, `troupe.cli.config` and `troupe.cli.commands` reaches
the core through `troupe.cli.commands._call`, which runs `troupe.core.client.dispatch.call` under `on_interrupt` in
an `asyncio` loop. The core's handlers need a git theatre: run in a plain directory, every command starts `git`
(probed 2026-11-26: `init` runs `git rev-parse --is-inside-work-tree`, the config and run commands
`git rev-parse --git-common-dir ...`). A unit test may not start a process or use a git theatre (the kinds detector,
`scripts/kinds_pytest.py`), and #507 counts an in-process `main([...])` and the functions underneath as unit.

## Goals / Non-Goals

**Goals:**

- Every line of the three modules runs in a unit test, through the same path a person's command takes: `main`, the
  parser, the command's function, `_call`, the real dispatcher.
- A test fails when the request sent, the text printed or the exit code changes.

**Non-Goals:**

- Testing the core's handlers: their own unit and integration tests do that.
- Sending a signal to the test process.

## Decisions

### D1. Stand in for the core through the dispatcher's `methods` argument

`dispatch.call` takes `methods=`, a table of method name to `Method(request, handler)`. The tests replace
`troupe.cli.commands.call` (the name `_call` calls) with `call` bound to a table of stand-ins, each with the method's
real request class (from `dispatch.handlers()`) and a handler that records the request and session, sends the updates
it was given and returns the result it was given.

Alternatives: replacing `_call` itself would leave `_call`'s own code (the loop, the Ctrl-C wiring) unrun and the
requests unparsed, so a request the core would refuse could pass. A git theatre is what the integration tests
already do, and is refused in a unit test.

### D2. Every request, update and result is a protocol message

The dispatcher parses each request with its request class, so a request the core would refuse fails the test as
`client.invalid-request`. Results and updates are built with the protocol's classes (`InitResult.from_data(...)`,
`Started(...)`, `NoticeUpdate(...)`), and the dispatcher returns their `to_data()`: a fixture can't be a shape troupe
never sends, as #522's tests did with the protocol's message classes.

### D3. Ctrl-C by calling the installed handler, not by sending a signal

To test what a Ctrl-C during `perform` or `logs --follow` does, the stand-in handler calls the SIGINT handler
`on_interrupt` installed (`signal.getsignal(signal.SIGINT)`) directly, once or twice, and then returns. That runs
`interrupted` and `pressed` exactly as a signal would, without sending one. `pressed` runs as a loop callback, and
asyncio logs an exception in a callback instead of raising it, so a broken `on_cancel` wouldn't fail the command: it
would print "Exception in callback" on the person's terminal. The stand-in captures what asyncio logs while a command
runs, and each Ctrl-C test asserts nothing was. Each run restores the interrupt handlers it found, so no change to
the CLI's code can leave the test process without one. Sending SIGINT to the test process
(`os.kill`) is left out: it would reach outside the call under test, and the orchestrator asks to be consulted before
any mutation run of code that sends signals.

### D4. One helper, beside the suites

The stand-in core lives in `packages/troupe/tests/cli_core_stand_in.py`, beside `unit/` and `integration/`, as the
kinds detector asks of what tests share (no test module imports another). It has no package path string literals, so
it doesn't widen which suites a path's change reaches. A fixture-free function (`stand_in(monkeypatch, theatre, ...)`)
keeps each test's setup visible in the test.

### D5. Tests by command family, one commit per module

`troupe.cli.init`'s tests extend `test_cli_init_unit.py`. `troupe.cli.config`'s go in `test_cli_config_unit.py`
(extended) and a new `test_cli_config_get_unit.py` for `get`, `sync`, `drop` and `keep`. `troupe.cli.commands`'s go
in new `test_cli_perform_unit.py` and `test_cli_queries_unit.py` (status, logs, diff, accept, discard). Each file
stays under the size gate's warning. Each module's tests land in their own commit, in the order init, config,
commands: the most score for the least work first.

### D6. Measured locally, on the unit tests only

With the check slot held: mutmut 3.8.1 in a throwaway clone with this branch's tests, the unit tests only, scoped
to the three modules, at most 2 children, `scripts/mutation.json`'s settings. On macOS the clone's copy of that file
sets `mutant_memory_mb` to null, since `RLIMIT_AS` raises there and would count every mutant caught. The repository's
copy is unchanged.

## Risks / Trade-offs

- [The stand-ins return what the test gives them, so a result the core would never return for that request can be
  rendered] → each result is still a valid protocol message; which result goes with which request is the core's
  integration tests' concern.
- [Replacing `commands.call` is patching a module global] → it's the one name between the CLI and the core, and the
  integration tests run the real one.
- [A survivor may be equivalent (a default the protocol always fills)] → each one left is listed in the pull request
  with why it can't be killed.
