# Tasks

## 1. The stand-in core

- [x] 1.1 Add `packages/troupe/tests/cli_core_stand_in.py` (design D1, D2, D4): replaces `troupe.cli.commands.call`
  with the real `dispatch.call` bound to stand-in methods that keep each method's real request class, record each
  call's method, request and session, send given updates and return a given result, all protocol messages; and a
  way for a stand-in to press Ctrl-C by calling the installed SIGINT handler (D3). Verify a test using it passes and
  reaches no process, socket or git theatre (the kinds detector passes it)

## 2. troupe.cli.init (#519)

- [x] 2.1 Extend `tests/unit/test_cli_init_unit.py`: the `--runner` without `--audition` refusal, the request sent,
  the made and rehearsed theatre with and without an actor, each step's commands and notes (each runner, the key's
  variable, its override and a malformed override, the token budget, the extra), notices, and exit codes. Verify the
  file passes; commit. Measured 2026-11-26: `troupe.cli.init` 412 of 423 killed (97.4%) before the last two tests
  (aimed at two of the 11 left; the final run in 5.1 measures them)

## 3. troupe.cli.config (#518)

- [x] 3.1 Extend `tests/unit/test_cli_config_unit.py` for `config set`, `unset` and `mv`: requests (reason,
  rehearse, typed values, the runner a value is typed for), the `path=value` refusal, entry, file and hand-edit
  lines, nothing changed, rehearsals and the recorded change. Verify the file passes
- [x] 3.2 Add `tests/unit/test_cli_config_get_unit.py` for `config get` (value, string, nothing set, empty, conflicts
  and shortened values, `--resolved`, `--json`), `sync`, `config drop` and `config keep`. Verify the file passes;
  commit. Measured 2026-11-26: `troupe.cli.config` 793 of 858 killed (92.4%) before the tests of notices and Ctrl-C
  during every config command, and the stand-in's refusal of a call with no session (aimed at most of the 65 left;
  the final run in 5.1 measures them)

## 4. troupe.cli.commands (#517)

- [x] 4.1 Add `tests/unit/test_cli_perform_unit.py`: the request, started, worktree, event and notice lines, a
  rehearsal's lines, each outcome's text and exit code, each settle hint, and one and two Ctrl-C presses. Verify the
  file passes
- [x] 4.2 Add `tests/unit/test_cli_queries_unit.py`: `status`, `logs` (followed entries, the run's lines, `--json`, a
  cancelled follow), `diff`, `accept` and `discard`, and the session each command runs in. Verify the file passes;
  commit

## 5. Measurement

- [x] 5.1 With the check slot held, run mutmut 3.8.1 locally on the unit tests only, scoped to the three modules, at
  most 2 children, with `scripts/mutation.json`'s settings (design D6). Verify each module scores over 60%, and
  record the scores and the survivors left (with why each is equivalent or out of reach) here and in the PR.
  Measured 2026-11-26 on every test of this change (the per-mutant memory cap nulled in the throwaway clone only:
  macOS refuses `RLIMIT_AS`, which would count every mutant caught): `troupe.cli.init` 415 of 423 killed (98.1%),
  `troupe.cli.config` 844 of 858 (98.4%), `troupe.cli.commands` 649 of 688 (94.3%). The 61 left change nothing a
  person or the core sees: 34 drop `flush=True` or make it falsy (a test's stream shows no flush); 8 pass
  `ensure_ascii=None` or `as_json=None` where `False` is meant, both falsy; 8 replace an `on_update` that ignores
  updates with `None` or one returning 0, which also ignore them; 4 leave out a `Session` argument whose default is
  the same value; 3 make an `isinstance` check of a value that's always a string always true; 2 spell a codec
  `UTF-8`, the same codec; 2 change `config drop`'s plural, but a drop always has at least 2 changes (the
  protocol's `minItems`); 1 upper-cases the field `env_name` upper-cases anyway
- [x] 5.2 Write each Ctrl-C test to fail when the handler's callback raises: asyncio logs an exception in a
  callback instead of raising it, so the stand-in captures what asyncio logs and each test asserts nothing was.
  Verify by applying the `on_cancel=None` mutant by hand: it logs "Exception in callback", and the test fails
- [x] 5.3 `uv run scripts/check.py` passes before each commit

## Workflow follow-up

- Draft PR closing #517, #518 and #519, with the local scores and survivors in its body (CI's mutation-pr report
  can't confirm a tests-only change; the next nightly run does); act on the review; archive on the branch before
  merge.
