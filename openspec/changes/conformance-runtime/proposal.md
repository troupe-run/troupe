# Proposal: conformance-runtime

## Why

troupe-run/troupe#299, from #297's split review. `contributing/runners.md` and `docs/stagecraft/bring-your-own-agent.md`
point runner authors at the env-driven conformance check (`TROUPE_CONFORMANCE_RUNNER` in
`packages/troupe/tests/test_runner_conformance.py`), but it passes no runtime and no credential. Pointed at the OpenAI
runner it fails 5 of 8 checks with `openai.no-runtime`. troupe's own runners that need a runtime are checked by their own
tests against stand-ins; an outside runner that talks to a service has no route at all.

## What Changes

- A new variable, `TROUPE_CONFORMANCE_RUNTIME`, gives the env-driven check a runtime: a JSON object holding the
  runtime's `name` and the fields a runtime has in config (`endpoint`, `model`, `credential: {env: ...}`, `prices`).
  It's checked as config checks a runtime, and resolved as a run resolves one: troupe's built-in runtime of that name,
  then the object, then the session's `TROUPE_RUNTIME_<NAME>_*` variables. So `{"name": "openai"}` is enough for a
  built-in, and an outside runner names its own service.
- The credential is a reference only, as everywhere else (#278): the object names the variable that holds it, never
  the value. Its value is read from the session's environment, given to the runner as `TROUPE_RUNTIME_CREDENTIAL` as a
  run gives it, and refused as a run refuses it (unset, malformed, too short to mask, sent over plain HTTP to a host
  that isn't loopback). No variable the check reads holds a secret.
- A malformed `TROUPE_CONFORMANCE_RUNNER`, `TROUPE_CONFORMANCE_OPTIONS` or `TROUPE_CONFORMANCE_RUNTIME` is refused with
  a message naming the variable and the fix, never read as absent; an unset one falls through as today.
- `check_runner` masks the credential in every check's problem, not only the whole run's, so a runner that echoes its
  key in a refusal doesn't put it in the test's output.
- The two docs say how to check a runner that needs a runtime and a credential, and drop the "can only be checked
  from code" and "can't yet check" notes.

Out of scope, as #299 says: changing the conformance checks themselves.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `actor-runners`: the conformance suite can be given a runtime and a credential by reference, through the
  environment as well as from code, and masks the credential in every check's result.

## Impact

- `packages/troupe/tests/test_runner_conformance.py`: reads the three variables, resolves the runtime, and passes it
  and the credential to `check_runner`; new tests, including the env-driven path checking the OpenAI runner against
  its stand-in with a credential named by reference.
- `packages/troupe/src/troupe/core/runners/conformance.py`: masks every check's problem.
- `contributing/runners.md` ("Checking a runner") and `docs/stagecraft/bring-your-own-agent.md` ("Check your runner").
- No protocol, schema or error-catalogue change; no new spec, so no `oob/troupe-spec-purposes.json` change.
