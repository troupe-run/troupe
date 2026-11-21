# Tasks

## 1. Mask every check's problem (D4)

- [x] 1.1 In `check_runner`, mask each check's problem with the run's credential. Add a test with a fake runner mode
  that refuses `run/start` with a problem holding the key it was given; verify the test fails before the change
  (the key appears) and passes after (`[credential]` in its place), and that the existing conformance tests still
  pass.

## 2. Read the conformance variables (D1, D2, D3)

- [x] 2.1 Write the differential tests first, passing on main: an unset `TROUPE_CONFORMANCE_OPTIONS` means `{}` and an
  unset `TROUPE_CONFORMANCE_RUNTIME` sends no runtime; run them against the current helper-less test body to confirm
  they hold before the rewrite.
- [x] 2.2 Add the helper in `test_runner_conformance.py` that reads `TROUPE_CONFORMANCE_RUNNER`, `_OPTIONS` and
  `_RUNTIME` from a mapping and returns the command, options, runtime and credential: refusing a malformed variable
  with a `ConformanceSetupError` naming it, checking the runtime object with `runtime_problems`, refusing a missing
  model in its own words, and resolving with `runtimes.for_run`. Have the env-driven test use it. Verify with tests
  for each spec scenario: built-in by name with an endpoint override, an outside runtime, no runtime, a credential
  reaching the runner as `TROUPE_RUNTIME_CREDENTIAL` and no other session variable, credential unset, insecure
  endpoint, a key in `credential.env` absent from the message, options not an object, an unknown runtime field, a
  bad runner command.
- [x] 2.3 Test the env-driven path end to end against the OpenAI-style runner and its stand-in with
  `{"name": "openai", "model": ..., "credential": {"env": ...}}` and an endpoint override: every check passes, the stand-in saw
  the key as the bearer token, no result holds it (D5). Verify it fails with no runtime given (#299's
  `openai.no-runtime` case) by running it once with the runtime left out, then restore.
- [x] 2.4 Update the module docstring to name the third variable and the credential-by-reference rule. Verify
  `uv run pytest packages/troupe/tests/test_runner_conformance.py` passes, and the documented command from
  `contributing/runners.md` runs as written against the scripted runner.

## 3. Document it

- [x] 3.1 `contributing/runners.md`, "Checking a runner": describe `TROUPE_CONFORMANCE_RUNTIME` with a worked example
  for a runner that talks to a service, the credential named by its variable, and drop "can only be checked from
  code". Verify the example's JSON parses and passes the helper's checks (run it against the OpenAI runner and a
  stand-in, or the scripted runner with a runtime).
- [x] 3.2 `docs/stagecraft/bring-your-own-agent.md`, "Check your runner": the same in user words, replacing the "can't
  yet check" note and the #299 link. Verify the rendered anchors still resolve and the example matches 3.1's.

## 4. Check

- [x] 4.1 `uv run scripts/check.py` passes (full log kept in the scratchpad), and
  `openspec validate conformance-runtime --strict` passes.

## Workflow follow-up

- Draft PR closing #299, act on Claude's review, mark ready, archive on the branch, owner merges.
- After the merge: check #299 is closed and its card says Done.
