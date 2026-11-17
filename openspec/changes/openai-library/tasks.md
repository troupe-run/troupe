# Tasks

The OpenAI runner moves onto `openai==3.52.0` (decision troupe#319) and ships as `troupe-run[openai]` (troupe#333's
mechanism, on main). Built on troupe#437 (`host-robustness`); the pull request opens only after #437 merges, rebased
onto main. #332 (Ollama) edits the same extras and docs in parallel: whichever merges second rebases.

## 1. Differential tests first (design D11)

- [ ] 1.1 Add the tests that state what must hold whichever HTTP stack the runner uses, and run them on today's runner
  before touching `service.py`: `OPENAI_*` variables change nothing (spec: "The library finds nothing of its own");
  `OPENAI_LOG=debug` puts no request header on standard error; only the runner retries (every request 500, the fake
  sees exactly the maximum attempts); a held connection is abandoned after the named stream timeout; a byte `0xff` in
  the stream is retried as `network`; the first request's body equals a recorded copy of today's. Verify: each passes
  on today's runner (`uv run pytest plugins/runner-openai/tests -k <names>`), output kept in the scratchpad.
- [ ] 1.2 Add the two tests that state this change's edges and fail on today's runner by design, each saying so: a
  whole final event without its blank line is retried as `network` (D5); the transcript's `received` records are
  events, not lines (D6). Verify: both fail on today's runner, and the failures are the expected ones.

## 2. The dependency (design D1, D10)

- [ ] 2.1 Add `openai==3.52.0` to `plugins/runner-openai/pyproject.toml` and lock it surgically
  (`uv lock --upgrade-package openai` from the committed lock, nothing else moving). Verify: a by-package diff of
  `uv.lock` adds `openai` and nothing else; `scripts/runner_licences.py` passes; each compiled dependency has wheels
  for cp312 to cp315 on Linux, macOS and Windows (they're `anthropic`'s, already checked).
- [ ] 2.2 Move `troupe-runner-openai` to `troupe-run`'s `openai` extra and `all`, set `in_extra=True` on core's
  `openai` runner entry, add the extra's row to `docs/opening-night/install.md`, and keep the bundle's commits out of
  release pull requests as `contributing/runners.md` lists. Verify: `scripts/bundle.py`, `scripts/release_config.py`
  and `scripts/tests/workspace/test_install_docs.py` pass; an actor on `openai` without the plugin is refused with
  `runner.not-installed` naming `troupe-run[openai]` (core's existing extras tests, with a case for `openai`).
- [ ] 2.3 Update the `cli` tests for the OpenAI audition with and without its extra (spec: cli). Verify: the
  `test_cli_init.py` cases pass.

## 3. The seam (design D1–D4, D7, D9)

- [ ] 3.1 Add `library.py` (clear `OPENAI_*`, quiet the library's loggers to standard error, masked and cut) and
  `failures.py` (status, network, not-a-stream, unreadable failures; no library import). Verify: unit tests for both,
  and the import contract that only `service.py` imports `openai` or `httpx2`, with a scratch module that imports it
  failing the check.
- [ ] 3.2 Rewrite `service.py` over `openai`: the runner's `httpx2.Client` (no redirects, named timeouts including
  the new `WRITE_TIMEOUT_SECONDS`, no proxy for a loopback endpoint), `max_retries=0`, the credential or the omitted
  `Authorization`, the content-type check, and D4's failure table; keep `parse_endpoint` and the endpoint checks.
  Verify: `test_openai_service.py` covers each row of D4's table and the client's settings, and every test from 1.1
  passes.
- [ ] 3.3 Change `stream.py` to read the library's event dicts (keeping `read_response` and the wrong-shape rules) and
  `exchange.py` to record what the library exposes, with lone surrogates as #437 left them. Verify:
  `test_openai_stream.py`, `test_openai_exchange.py` and the fixture replay (`test_openai_fixtures.py`) pass with the
  fixtures unchanged; an unknown field in an event reaches the transcript.
- [ ] 3.4 Stop the request in flight by ending the process (D8): the in-flight flag under the output lock, the worker
  importing the library after `run/start`, a background warm-up import. Verify: the cancel and end-of-input tests in
  `test_openai_runner.py` pass, the runner exits within troupe's grace with a request held open, and the conformance
  suite passes.

## 4. Docs and the rest of the runner

- [ ] 4.1 Update the runner's README (the library, the extra, the named timeouts, what the transcript holds and
  loses, no line limit), `contributing/runners.md` where it names the OpenAI runner as hand-written, and the module
  docstrings that cite design D3. Verify: `test_openai_readme.py` and the docs checks pass; `grep -rn "urllib"
  plugins/runner-openai/src` finds nothing.
- [ ] 4.2 Run the whole check once, when the load is under ~40 (`uptime` first). Verify: `uv run scripts/check.py`
  passes, its full output kept in the scratchpad.
- [ ] 4.3 Ask the owner, through the orchestrator, to run the live test (`TROUPE_LIVE_OPENAI=1`) with their key, or
  to say to go without it. Verify: the owner's result, or their word, is recorded on the pull request.

## Workflow follow-up

- Open the draft pull request only after #437 has merged, rebased onto main with every commit signed off.
- Act on Claude's review, mark ready once it's clean, run `/openspec-archive-change` on the branch, and hand the owner
  the merge command through the orchestrator.
- After the merge, check #331 is closed and its card says Done.
