# Proposal: the OpenAI runner uses the openai package

Issue: [troupe#331](https://github.com/troupe-run/troupe/issues/331), decided in
[troupe#319](https://github.com/troupe-run/troupe/issues/319) (runner plugins may depend on maintained client
libraries, and keep troupe's guarantees themselves), installed as [troupe#333](https://github.com/troupe-run/troupe/issues/333)
says (an optional extra named after the runner). The runner speaks the Responses API only
([troupe#290](https://github.com/troupe-run/troupe/issues/290)). Built on
[troupe#437](https://github.com/troupe-run/troupe/pull/437) (`host-robustness`), which changes how runners read lone
surrogates and write their output.

## Why

The OpenAI runner talks to its service through its own HTTP client: `urllib` with a redirect handler, a captured
socket for timeouts and aborts, and a hand-written server-sent events parser. The `openai-style-runner` design (D3)
turned the `openai` package down, partly out of habit (no dependency beyond the SDK) and partly because the package
retries on its own terms, follows redirects and hides the wire bytes the transcript kept. Decision #319 settled each of
those for every runner: a runner should prefer a maintained client library, turns the library's retries off and keeps
troupe's, never follows a redirect, keeps the credential to its header, and records in its transcript what the library
exposes. #333 made the extras that carry such a runner, and the Anthropic runner (#415) has since shown the pattern
works with the same generator's library (`anthropic`, also on `httpx2`). This change moves the OpenAI runner onto
`openai`, so troupe stops maintaining a second HTTP and SSE stack for an API OpenAI maintains a client for.

## What Changes

- **The runner sends every request through the `openai` package**, pinned (`openai==3.52.0`), as a streamed
  `responses.create` call, through one module that alone imports it. The request it sends is the same body as today.
  The library's own retries are off (`max_retries=0`), its HTTP client is the runner's (no redirects, the runner's named
  timeouts), and it finds no credential, base URL, organisation, project or header of its own: the runner clears every
  `OPENAI_*` variable from its own environment and gives the library everything itself.
- **`troupe-run[openai]`.** The plugin leaves `troupe-run`'s base dependencies for an `openai` extra, and `all`. An
  actor on the `openai` runner without it is refused with `runner.not-installed`, naming `troupe-run[openai]`, as #333
  built; `troupe init --audition --runner openai` names the extra; the install page lists it.
- **The transcript keeps what the library exposes** (#319, #294's kinds): each request's parameters as passed to the
  library (`sent`), each stream event as the library parsed it and each error body (`received`), and the status, kept
  headers and abandoned streams (`note`), as the Anthropic runner records them. Compared with today's wire bytes it
  loses the SSE framing (`event:` lines, blank lines, comments), and the request body becomes the parameters before the
  library serialises them. The design lists the rest.
- **Every other behaviour the spec promises stays**, proved by today's fixtures and tests replayed through the same fake
  endpoint, with tests written first against today's runner (differential), and re-captured only where the transcript
  honestly changes. Two edges change where the library reads the stream differently, each made explicit in the spec:
  a final event that the body ends right after, without its blank line, is now retried as a cut stream rather than
  read (the library dispatches an event only on its blank line); and a request in flight at cancel is abandoned by
  ending the runner's process, as the Anthropic runner does, since closing the library's stream from another thread
  doesn't wake a blocked read.
- **The library's logging stays out of the run's output**, whatever `OPENAI_LOG` says, and the pydantic serialiser's
  warnings about the service's wrong shapes don't reach standard error as noise.
- **Licence and platforms:** `openai` and everything it pulls in pass `scripts/runner_licences.py`, and
  `troupe-run[openai]` installs on Linux, macOS and Windows for every supported Python (the install check covers
  `troupe-run[all]`).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `openai-runner`: the runner talks to its service only through the `openai` package; the library finds nothing of its
  own; its logging stays out of the output; every library timeout is a named setting; its dependencies are licensed and
  install everywhere; the transcript is what the library exposes; a stream's lines are capped below the library; a
  broken stream and a wrong-shaped response say when an event counts as finished; cancel abandons the request by
  ending the process.
- `cli`: the OpenAI audition needs its extra, and is refused naming `troupe-run[openai]` without it.

## Impact

- `plugins/runner-openai`: `service.py` becomes the seam over `openai` (with `library.py` for its environment and
  logging and `failures.py` for the failure types, neither importing it); `stream.py` reads the library's events
  instead of SSE lines; `exchange.py` records what the library exposes; `runner.py` stops the request in flight by
  ending the process; the capture tool and the README follow. The fixtures' `replies.json` (what the service sent) stay
  as they are; their `expected.json` changes only where it holds transcript records.
- `packages/troupe-run/pyproject.toml`: the plugin moves to the `openai` extra and `all`; core's runner table marks
  `openai` `in_extra`; the install page gains a row; release configuration as the bundle check requires.
- `uv.lock`: `openai` 3.52.0. Its dependencies (`anyio`, `httpx2`, `jiter`, `pydantic`, `sniffio`,
  `typing-extensions`) are already locked for the Anthropic runner.
- Runs on the built-in `openai` runtime need `troupe-run[openai]`. An install of `troupe-run` alone loses the OpenAI
  runner, which is #333's design, not a regression.
- #332 (Ollama onto `ollama`) runs in parallel and touches the same extras and install docs; whichever merges second
  rebases.
