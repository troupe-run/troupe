# Proposal: runner-extras

## Why

Decision #319 (owner, 2026-11-07) lets a runner plugin depend on a maintained client library for its engine, such as
`openai`, `ollama` or `lmstudio`. Today `troupe-run` depends on every plugin, so every install would carry every
runner's libraries (pydantic, msgspec, jiter, httpx and more). The decision's points 2 and 3 settle what happens
instead. Each library-backed runner becomes an optional extra of `troupe-run`. An actor on a runner that isn't
installed is refused, naming the extra. And the guarantees a library mustn't decide for troupe are written down
once. Issue #333 tracks this. #291 (LM Studio), #331 (OpenAI) and #332 (Ollama) are waiting on it to add the first
library-backed runners.

## What Changes

- **An extra for each library-backed runner, plus `all`.** A runner plugin that depends on anything beyond the plugin
  SDK is in `troupe-run`'s optional dependencies, under an extra named after the runner (`troupe-run[lm-studio]`,
  `[openai]`, `[ollama]`). It isn't in the base dependencies. A runner whose only dependency is the SDK stays in the
  base install, and isn't an extra. `troupe-run[all]` installs every runner plugin. Which side a runner goes on
  follows from its own `pyproject.toml`, not anyone's judgement, and the repository's check enforces it. No shipped
  runner has a library today, so this change builds the mechanism, and `all` adds nothing to the base yet. #291,
  #331 and #332 add the first extras.
- **The bundle's pins and release rules cover the extras.** A pin in an extra has the same form as a base pin. The
  pinning pull request moves it the same way. A bare member named in an extra holds back the bundle's release the
  same way.
- **An actor on a runner that isn't installed is refused, naming its extra.** There's a new error code,
  `runner.not-installed`, with the runner, its package and its extra (null for a base runner). It's raised for
  `troupe config set` on that actor, at run start (before anything is recorded) and for `troupe init --audition
  --runner <name>`. Its fix names `troupe-run[<extra>]` and the install page, or, for a base runner, reinstalling
  troupe or `uv sync` in a checkout. Checks of the whole config (other actors' changes, merges) don't refuse because
  someone else's actor uses a runner that isn't installed here.
- **Init says which extra a runner needs.** An audition on a library-backed runner says in its next steps that the
  runner comes with `troupe-run[<extra>]`.
- **The guarantees, recorded once in the runner-protocol spec.** Retries, backoff and `Retry-After` follow troupe's
  named limits, with the library's own retries off. Redirects aren't followed. The credential goes only in its
  header and is never logged. Cancel and end of input stop the request in flight within the grace period. Every
  limit is a named setting. The transcript keeps each request and response as the library exposes them, serialised,
  not necessarily as wire bytes, and the runner's design says what that loses. The record kinds themselves are
  #294's to add, and that issue is still open. And each of a
  runner's dependencies is pinned in the lock file and has a licence compatible with Apache-2.0. A new check
  enforces the licence part in two tiers: permissive, and weak-copyleft (MPL-2.0, for `certifi`). The
  weak-copyleft tier is allowed only as unmodified separate packages (owner, #333 comment 6707703235).
  `contributing/runners.md` links to the requirement and explains how to add an extra.
- **The install check and the install page cover the extras.** The install page documents the extras form of the
  command, and the docs check checks it like the plain form. On Linux, macOS and Windows, on every supported Python,
  the install check installs the base and then `troupe-run[all]`. It confirms that every runner troupe knows is
  available after `[all]`, and that, in the base install, each extra runner is refused naming its extra. The release
  install check does the same for a published tag.
- **BREAKING** (for anyone relying on it, pre-1.0): `troupe-run` no longer promises every runner. Once a runner moves
  into an extra, a plain install no longer has it.

Not in this change: moving any runner onto a library (#291, #331 and #332), and removing the ollama-runner
requirement that the plugin "SHALL declare no dependency other than the SDK". #332 removes that with the move, since
it stays true until then.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `installation`: `troupe-run` depends on every package and every SDK-only runner plugin. It has an extra per
  library-backed runner, plus `all`. The documented extras form of the command. The install check and the release
  install check install `[all]` too, and check each runner is available or refused.
- `releases`: the bundle's pin, pinning pull request and bare-member release rules cover its extras.
- `runner-protocol`: the guarantees a runner keeps when it uses a client library, and its dependencies' pins and
  licences.
- `runs`: perform refuses an actor whose runner troupe knows but isn't installed with `runner.not-installed`, before
  anything is recorded, and troupe's runner table says each runner's extra.
- `config`: setting an actor on a runner that isn't installed is refused with `runner.not-installed`. A whole-config
  check doesn't refuse for another actor's uninstalled runner.
- `cli`: `troupe init --audition --runner <name>` refuses an uninstalled runner, naming its extra, and an audition on
  a library-backed runner names its extra in its next steps.
- `protocol`: the missing-plugin refusal no longer says an install brings every runner, and `runner.not-installed`
  is catalogued.

## Impact

- `packages/troupe-run/pyproject.toml`: `[project.optional-dependencies]`, with `all` and no runner extras yet.
- `packages/troupe/src/troupe/core/interim.py`: each `Runner` gets its `extra`, and `runner()` refuses with
  `runner.not-installed`. Also `core/config/kinds.py`, `core/audition.py`, `cli/init.py`, `core/schemas.py`'s
  missing-plugin fix, `core/errors.py` and the protocol's error catalogue (`error.schema.json`, both copies).
- `scripts/bundle.py`, `scripts/pin_bundle.py`, `scripts/release_config.py`, `scripts/install_check.py`,
  `scripts/docs_reference.py`, with a new licence check of runner dependencies, and their tests.
- `.github/workflows/ci.yml` and `release-install-check.yml`, `docs/opening-night/install.md`, `README.md`,
  `packages/troupe-run/README.md` and `contributing/runners.md`.
- No spec is added or removed, and no Purpose changes, so troupe-run/infrastructure's `oob/troupe-spec-purposes.json`
  needs no update.
- Coordination: #291's pull request stays unready until this merges, and then adds `troupe-run[lm-studio]`.
