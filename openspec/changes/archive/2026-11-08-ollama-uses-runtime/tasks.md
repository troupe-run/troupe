# Tasks

## 1. The runner reads its runtime

- [x] 1.1 Add `troupe_runner_ollama/runtime.py` (design D2): `Runtime(name, endpoint, model)` and `from_run_start`,
  refusing `ollama.no-runtime`, `ollama.credential-unsupported` (without reading `TROUPE_RUNTIME_CREDENTIAL`) and
  `ollama.invalid-runtime`. Move the endpoint regex and its messages from `options.py`, with `where`
  `runtime.endpoint`, and fixes naming `runtimes.<name>.endpoint` and `TROUPE_RUNTIME_<NAME>_ENDPOINT`. A path's
  message says the native API is at the root and a `/v1` address is for the `openai` runner (D4). Verify: unit tests
  for each refusal, the endpoint property tests carried over from `test_ollama_options.py`, a test that a canary
  credential appears in no refusal, and a test that the runner's variable name matches core's rule for `ollama`,
  `openai` and `lm-studio`.
- [x] 1.2 Drop `model` and `endpoint` from `options.py`'s `Options` and parser, and `DEFAULT_ENDPOINT` from
  `defaults.py` and the README's limits table. Verify: `test_ollama_options.py` shows `{}` is accepted and `model` and
  `endpoint` are refused with `ollama.unknown-option`, and the README limits test passes.
- [x] 1.3 Update `schemas/options.schema.json` (no `model` or `endpoint`, no `required`) and `schemas/errors.schema.json`
  (the three new codes). Verify: the parser-and-schema agreement property test and the protocol strictness check
  pass.
- [x] 1.4 Wire the runtime through `runner.py`: refuse in the order params, options, runtime, preflight. Preflight and
  the conversation take the endpoint and model from the `Runtime`, the `init` event's `engine.model` is the runtime's,
  and `ollama.unreachable`'s fix names the runtime's config path and variable. Verify: `test_ollama_runner.py`, with
  the harness sending a `runtime`, covers each spec scenario under "The service comes from the run's runtime", "The
  runtime's endpoint is one the runner can use", "A runtime with a credential is refused", "Init for a run" and
  "Ollama isn't running".
- [x] 1.5 Move the capture tool and fixtures to the runtime (D7): scenarios get a `model` field, and their options and
  the fixtures' `provenance.options` drop `model`. Only provenance is edited. Verify: `test_ollama_fixtures.py`
  replays every fixture to exactly its recorded events and transcript, and `test_ollama_capture.py` passes.
- [x] 1.6 Update the runner's README: its service comes from a runtime, its options table, the new error codes, and how
  to point it at another host. Verify: `test_ollama_readme.py` passes, and
  `uv run scripts/check.py --scope runner_ollama` passes.

## 2. Core: the runner table, moved options and the audition

- [x] 2.1 Set `RUNNERS["ollama"].runtime = "required"` in `core/interim.py`, and replace its comment about the endpoint
  being an option (D1). Verify: a config test refuses `actors.tester.runner=ollama` without a runtime, naming
  `actors.tester.runtime` and listing the runtimes, and the runner-table test shows `ollama` and `openai` required.
- [x] 2.2 Add `MOVED_TO_RUNTIME` beside the runner table, and the moved-option problem with its fix built from the
  actor alone in `core/config/kinds.py` (D5, the owner's static form). The schema's "no such field" problem and the
  missing-runtime problem for the same actor are left out. Verify: `test_config_kinds.py` covers each scenario
  under "Options a runner moved to its runtime are refused with the move": the audition's model, other options
  kept, the default endpoint, an endpoint on another host (a `<name>` to choose, nothing under `runtimes.ollama`),
  and an unrelated change. A CLI test runs the audition-shaped fix exactly as given (`shlex`-split), then checks
  config is valid and the actor names `ollama` with the model.
- [x] 2.3 Check that perform refuses an old actor with the same rule, recording nothing. Verify: a
  `test_perform_ollama.py` test with an actor holding `options.model` fails with `config.invalid` and that fix, and
  the event store is unchanged.
- [x] 2.4 Change the Ollama audition (`core/audition.py`) to `runtime: ollama`, `model`, and no options, and
  `cli/init.py`'s note to read the actor's `model` (D6). Verify: `test_cli_init.py`'s Ollama scenarios check
  `lead.yaml` holds runtime and model and no options, that no `.troupe/runtimes/` file is written, and that the note
  names `ollama pull <model>`. The Ollama journey runs against its stand-in through
  `TROUPE_RUNTIME_OLLAMA_ENDPOINT`.
- [x] 2.5 Move core's Ollama tests off `options.endpoint` (`test_perform_ollama.py`, `test_ollama_host.py`,
  `test_runner_conformance.py`, and any config test that names it), using a runtime that points at the stand-in.
  Verify: the conformance suite passes against the Ollama runner with a runtime and no credential, a perform test
  shows the run's start records the runtime `ollama` with the actor's model, and `uv run scripts/check.py` passes.

## 3. Docs

- [x] 3.1 Update `docs/stagecraft/runtimes.md` (drop the note that the runner still takes its options, say the
  Ollama runner requires a runtime, and the move for an old actor), `docs/stagecraft/bring-your-own-agent.md`'s
  Ollama entry, and `docs/opening-night/first-performance.md`'s Ollama section (the actor's `runtime` and `model`, and
  another host via `runtimes.<name>.endpoint` or `TROUPE_RUNTIME_OLLAMA_ENDPOINT`; it links to `runtimes.md`, and a
  newcomer has no old actor to move). Check that
  `docs/prompt-book/config-schema.md` (generated, and it names no runner) and `cli.md` need nothing. Verify:
  `uv run scripts/check.py` passes, including the docs checks and any walkthrough test that runs the Ollama page as
  written.

## 4. Integration

- [x] 4.1 Run the live test against a local Ollama (`TROUPE_LIVE_OLLAMA=1`) with the audition actor as `init` now
  writes it. Verify: it's skipped without the variable, and the run `succeeded`, with the output shown.
  Done: on Ollama 0.40.14 with `qwen3.5:4b`, the live test `succeeded` (events `init`, `tool_call`, `tool_result`,
  `turn`, `result`; it wrote `out/hello.txt` holding `hello`). `troupe init --audition --runner ollama` then
  `troupe perform lead` in a new repository also `succeeded`, and the run's start recorded the runtime `ollama`, its
  endpoint from `default` and the model `qwen3.5:4b` from `actor`.
- [x] 4.2 Run `uv run scripts/check.py`. Verify: it passes locally, and CI passes on Linux, macOS and Windows on the
  last code change once the PR is marked ready.
  Done: passes locally, and CI run [42378312160](https://github.com/troupe-run/troupe/actions/runs/42378312160)
  passed all twelve legs on 373320c, the branch head. macOS with Python 3.13 failed once on an unrelated flaky Claude
  Code runner test (#337) and passed when re-run.

## Workflow follow-up

- Raise a follow-up issue (on the board, 0.2.0 or later per the owner) to send a credential to an Ollama service that
  takes one, or to refuse it before the run's start is recorded (design D3), if the owner wants it.
- Act on Claude's review, archive on the branch, and hand the PR to the owner to merge.
- After the merge, comment on #289 with the PR and the archived change, check it's closed, and check its card says
  Done.
