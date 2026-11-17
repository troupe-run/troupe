# Proposal

## Why

Decision #319 (owner, 2026-11-07), point 4: the Ollama runner moves off its hand-built HTTP client onto a maintained
library, and the ollama-runner spec's "SHALL declare no dependency other than the SDK" goes. Feature #332 tracks it,
and #333 (merged in #338) made a runner with a library an optional extra of `troupe-run` that keeps troupe's
guarantees itself. The runner changes that had to land first (#289, #282 and #309) have merged.

#319 named the `ollama` package. A probe of `ollama` 0.6.3, its latest release (findings on #332,
issuecomment-6947159287), found its public API can't keep the spec:

- it can't send `truncate: false` or `shift: false`, so Ollama would cut an over-long conversation silently;
- it strips `additionalProperties` and `minimum` from the SDK's tool schemas;
- it drops `prompt_eval_cached_count` and each tool call's `id`, and raises on arguments sent as a string;
- it has no `/api/version` call and no line-length cap.

The owner chose a maintained HTTP library directly (2026-11-17, #332 issuecomment-6947222534): `httpx2`, pydantic's
maintained fork of the `httpx` that `ollama` uses, and the stack the Anthropic runner and #331's OpenAI runner are
already built on, so `troupe-run[all]` carries one HTTP stack.

## What Changes

- The Ollama runner talks to Ollama through `httpx2` and its transport layer `httpcore2` (both BSD-3-Clause, pinned
  exactly), not the standard library's `http.client`. They bring `h11`, `anyio`, `idna` and `truststore`, all
  permissive and already locked. One module uses them, and the rest of the runner is unchanged.
- **BREAKING (install):** the Ollama runner leaves `troupe-run`'s base install. It becomes the `troupe-run[ollama]`
  extra, and `all` lists it. An actor on `ollama` without the extra is refused with `runner.not-installed`, naming
  `troupe-run[ollama]`, as #333 built. The install page, the first-performance guide and the runner's README say so.
- The HTTP client is the runner's own, set up so it decides nothing for itself:
  - it follows no redirect;
  - its timeouts come from the runner's named settings;
  - it does no retries of its own;
  - it reads nothing from the environment: no proxy, no `.netrc` credential, no certificate variables;
  - it sends no credential.
- What the runner sends and reads doesn't change: every request byte for byte, its tools, `num_ctx`, `truncate` and
  `shift`, the preflight's version and model calls, the line-length cap, the retries, cancel within the grace, the
  transcript as wire bytes, and every event. The existing fixtures and conformance tests prove it, with no
  re-capture, and differential tests against today's client come first.
- The ollama-runner spec's no-dependency requirement goes. It's replaced by the plugin's pinned dependencies and its
  extra, and a requirement that the HTTP client takes nothing from the environment and follows no redirect.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `ollama-runner`: "The Ollama runner is a self-contained plugin" names its pinned dependencies (`httpx2`, `httpcore2`)
  and its `troupe-run[ollama]` extra in place of "no dependency other than the SDK". A new requirement says its HTTP
  client takes no host, proxy, credential or header from the environment, and follows no redirect.
- `cli`: init's audition scenario for `--runner ollama` needs the extra installed, and a new scenario covers the
  refusal naming `troupe-run[ollama]` without it.

## Impact

- `plugins/runner-ollama/`:
  - `pyproject.toml`: the dependencies;
  - `client.py`: onto `httpx2`, keeping its interface and its failure classes;
  - `defaults.py`: any new named timeout;
  - the README: install, and the HTTP client's settings;
  - tests: differential tests against the old client, redirects, the environment, and cancel before and during a
    stream.
- `packages/troupe-run/pyproject.toml`: the base dependencies, the `ollama` extra and `all`. Also `uv.lock`.
- `packages/troupe/src/troupe/core/interim.py`: `in_extra=True` for `ollama`. Also the core tests that list which
  runners are extras, and those that import `troupe_runner_ollama`.
- Docs:
  - `docs/opening-night/install.md`: the extra's row;
  - `docs/opening-night/first-performance.md`, `docs/stagecraft/bring-your-own-agent.md` and `docs/prompt-book/cli.md`
    where they say how to get the runner;
  - `contributing/runners.md`: "Mapping an engine: Ollama".
- #331 (the OpenAI runner onto `openai`) is in flight in parallel and touches the same extras, interim test and install
  docs. Whichever merges second rebases.
- This change is built on #437 (`host-robustness`), which changes how runners write their output. Its pull request
  opens only after #437 merges, rebased onto main.
