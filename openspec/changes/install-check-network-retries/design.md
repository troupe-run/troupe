# Design: the install check rides out a short PyPI outage

## Context

See proposal.md for why. `scripts/install_check.py` runs `uv tool install` twice (the base install and
`troupe-run[all]`), each through `run("install…", argv, cwd, env, INSTALL_TIMEOUT)`, with `env` built by
`Tools.environment(os.environ)`, which adds the check's own `UV_TOOL_DIR` and `UV_TOOL_BIN_DIR`. CI's `check-legs` job
runs it last, after `uv run scripts/check.py`, with `timeout-minutes: 20`; `release-install-check.yml` runs the same
script with `--hosted`.

Measured with uv 0.13.7 (the version the failure ran is in the same series), against local addresses:

| What | Result |
|---|---|
| A connect to an unreachable address | about 10 s per attempt (uv's connect timeout) |
| `UV_HTTP_RETRIES=6`, connection refused each time | `Request failed after 6 retries in 50.7s`: backoff of roughly 1, 2, 4, 8, 16 s and more |
| The incident, defaults | `failed after 3 retries in 48.6s`: four 10 s connects plus about 8 s of backoff |
| A package PyPI doesn't have, `UV_HTTP_RETRIES=10` | `No solution found` in 0.7 s: a 404 isn't retried |
| `UV_HTTP_RETRIES=abc` | `Failed to parse environment variable UV_HTTP_RETRIES with invalid value abc` |

The failing leg (job 130266874925) took 17 min 16 s of its 20: the check 14 min, the install check 53 s to its failure.

## Goals / Non-Goals

**Goals:** outlast an outage of up to about two minutes on any one request; keep a real failure immediate; keep the
setting in one named place; keep a leg that does hit a long outage inside its job timeout, so it fails with uv's
message rather than as a cancelled job.

**Non-Goals:** retrying the whole install check, or the CI job, on failure; changing the workflows; covering
`uv sync --locked` (D4).

## Decisions

### D1. More retries, not longer timeouts

The incident was four connect timeouts in a row. A longer connect or read timeout (`UV_HTTP_CONNECT_TIMEOUT`,
`UV_HTTP_TIMEOUT`) only makes each attempt wait longer, with the same number of attempts and no backoff between them,
so it outlasts less of an outage per second spent. More retries add attempts spread out by uv's exponential backoff,
which is what spans an outage. So the check sets `UV_HTTP_RETRIES` only and leaves uv's timeouts at their defaults.

Alternatives: both retries and a longer timeout (two knobs for one effect, and a hung connection waits longer before
it's retried); wrapping the install in a retry loop of our own (re-resolves everything, and can't tell a network
fault from a resolution failure, which uv already can).

### D2. Six retries

`HTTP_RETRIES = 6`, a named module constant beside `INSTALL_TIMEOUT` and `COMMAND_TIMEOUT`, with a docstring saying
what it's for and how the number was chosen. Six retries give a request seven attempts over about 51 s of backoff,
so a refused or failing index is outlasted for about 50 s and an unreachable one (10 s connects) for about 2 min, two
and a half times what the incident got. Seven would back off for about 2 min more and reach about 3.5 min; on the
slowest leg's 17 min 16 s plus the 53 s already spent, that leaves too little of the 20 min. With six, a leg that
fails anyway ends about 70 s later than today, around 18.5 min.

The number doesn't scale with the install's own `INSTALL_TIMEOUT` (600 s): an outage long enough to fail six retries
fails the install step well inside it.

### D3. The caller's value wins; uv judges it

The check adds `UV_HTTP_RETRIES` to the environment it gives uv only when the variable isn't already in the
environment it was run with. Present means present: an empty or malformed value is passed through, and uv refuses it,
naming the variable and value, which the check reports as the install step's failure with uv's output. That follows
"only an absent input may fall through": the check never replaces a value it was given with its own.

It goes in the same place the tool directories are added (`Tools.environment`, or a small function it calls), so
both `uv tool install` runs, and anything later added to them, get it. The `troupe` commands the check runs see the
variable too, which is harmless: troupe doesn't read it.

Alternative: a workflow-level `env:` in `ci.yml` and `release-install-check.yml`. That's two places, and a developer's
own run wouldn't get it.

### D4. `uv sync --locked` stays as it is

CI's `Install` step runs before the check, from setup-uv's restored cache, and hasn't failed this way. Covering it
would need the value in `ci.yml` as well, since a workflow can't read the script's constant, so it would no longer
be in one place (a test could keep the two equal, at the cost of a second copy). In the 100 failed CI runs since
2026-10-15 the `Install` step failed none (the check failed 726 jobs, the install check 9). The owner decided
(2026-11-11) to leave it out: an occasional failure when an index is down there is acceptable.

### D5. Tested against a local index, not PyPI

The tests serve a minimal package index from a thread in the test (`http.server` on `127.0.0.1`, port 0) holding one
hand-built pure-Python wheel, and count the requests it receives:

- **First four requests fail, then serve** (the spec's first scenario): the index answers the package's page with
  `503` four times, then serves it. With the check's environment, the install succeeds. Four failures need a fifth
  attempt, which uv's default of three retries doesn't make; the test confirms that by running the same install with
  `UV_HTTP_RETRIES=3` and seeing it fail first. It waits about 15 s of backoff, so it's the slowest of the new tests.
- **Not found**: the index answers `404`. The install fails, naming the install step and uv's output, and the index
  saw exactly one request for that page.
- **Outlasted**: the index always fails, with `UV_HTTP_RETRIES=1` set by the caller to keep it short. The install
  fails, naming the step, and the index saw two requests, which also shows the caller's value was used.
- **Malformed**: `UV_HTTP_RETRIES=abc`; the step fails and its output names `UV_HTTP_RETRIES` and `abc`.

Each runs `uv tool install` through the check's own `run` and environment, into a scratch tool directory, with
`--no-cache` and `--index-url` the local index, so nothing reaches the network or the developer's own uv state. A unit
test checks the environment itself: the named value when absent, the caller's when present, on top of the tool
directories.

## Risks / Trade-offs

- [uv changes its backoff or its default retries] → the constant is named and its docstring says how it was sized;
  the first-scenario test fails if four failures stop being outlasted.
- [An outage on many requests at once still fails] → each request has its own retries, and they run concurrently, so
  a two-minute outage costs about two minutes, not two per package.
- [The check job's 20 min is already tight on the slowest leg] → D2 keeps a failing leg near 18.5 min; the job's
  timeout is unchanged, and raising it is a separate decision if the check itself grows.
- [The local-index test is slow (about 15 s)] → it's one test; the others use one retry or none.

## Migration Plan

None: the next CI run after the merge uses it. Rollback is reverting the commit.
