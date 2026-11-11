# Proposal: the install check rides out a short PyPI outage

## Why

The merge queue dropped #372 after every gate on its `check (macos-latest, Python 3.15)` leg had passed (run
42942338213), because the install check that runs last couldn't reach PyPI:

```
error: Request failed after 3 retries in 48.6s
  cause: Failed to fetch: https://pypi.org/simple/eventsourcing/
  ...
  cause: operation timed out
```

#372 touched no dependency and no part of the install check, and the same check passed on all twelve legs on its own
head. uv's default of three retries, about 50 s of connect timeouts and backoff, didn't outlast a short outage on one
runner. The owner had to queue the pull request again, and rounds 3–4 (#328, #325) wait behind the queue. Issue #375.

## What Changes

- The install check sets uv's network retries in one named setting in `scripts/install_check.py`, beside its
  existing `INSTALL_TIMEOUT` and `COMMAND_TIMEOUT`, and passes it to every `uv tool install` it runs. That covers CI's
  install check on every leg, the release install check (`release-install-check.yml`, which runs the same script with
  `--hosted`), and a developer's own run.
- The budget is sized so that an outage of up to about two minutes on one request is ridden out, but a leg's
  20-minute job timeout still isn't reached (design D2).
- A failure that isn't a network fault, such as a package that doesn't resolve or a requirement with no solution,
  isn't retried by uv, so it still fails at once, naming the step and uv's output, as today.
- A value the caller already set in the environment (`UV_HTTP_RETRIES`) is kept, not overridden. A malformed one is
  refused by uv, naming the variable, and the check reports that as the install step's failure (design D3).

Out of scope: CI's `uv sync --locked` step (the `Install` step before the check). It didn't fail, it runs from
setup-uv's cache, and covering it would need a second place for the setting, since a workflow can't read the
script's constant. The owner decided to leave it out (design D4).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `installation`: a new requirement that the install check outlasts a short network outage while a real install
  failure still fails at once.

## Impact

- `scripts/install_check.py`: the named retry setting, applied to the environment of each `uv tool install`.
- `scripts/tests/workspace/test_install_check.py`: unit tests for the environment, and a test against a local index
  that fails more often than uv's default retries allow and then serves, and one that serves "not found".
- `contributing/` docs that describe the install check, if any name its timeouts.
- No change to the workflows, troupe's packages, or any dependency. No new spec, so no `oob/troupe-spec-purposes.json`
  update in troupe-run/infrastructure.
