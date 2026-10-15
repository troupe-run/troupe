# Proposal

## Why

Every package declares `requires-python = ">=3.12"`, which claims support for every future Python, while CI tests
only 3.12 and 3.13. During the flake hunt (#100), a Windows PC with Python 3.15 installed ran troupe on 3.15, a
version CI has never run, and nothing said so. Issue #104 asks for the supported versions to be exactly the ones CI
tests, with the build enforcing that.

This change is Part 1 of #104, tracked as its sub-issue #105: enforce the versions CI tests today. Part 2
(adding 3.14 and 3.15 to CI and widening the bound) is a separate change that follows. Part 1 doesn't depend on
it, and the issue lets Part 1 land first.

## What Changes

- **An upper bound.** `requires-python = ">=3.12,<3.14"` in all nine `pyproject.toml` files: the workspace root,
  the seven packages under `packages/`, and `plugins/runner-scripted/`. `uv.lock` is re-locked. uv then refuses to
  sync or run troupe on 3.14 or later and names the bound. This was checked with uv 0.13.1: `uv run --python 3.14`,
  `UV_PYTHON=3.15` and a `.python-version` of 3.15 are all refused with
  `incompatible with the project's Python requirement: >=3.12, <3.14`.
- **A default interpreter.** A new `.python-version` holds `3.12`, the lowest supported version, so plain `uv run`
  uses it on every machine.
- **Switching versions in one command.** `uv run scripts/on.py 3.13 scripts/check.py` runs any command on any
  supported version, in that version's own environment (`.venvs/3.13/`). Switching back and forth on one machine
  doesn't rebuild or overwrite the default `.venv`, and two terminals on different versions don't clash. A version
  outside the bound is refused, and the refusal lists the supported versions. The owner asked for this on
  2026-10-15: test 3.12, 3.13 or 3.14 on one machine "with a basic change, not a bunch of messing around". 3.14
  becomes switchable when Part 2 widens the bound. See design D5.
- **One decision, checked in one place.** A new standard-library check, run as a test inside `scripts/check.py`,
  fails and names the file to fix when:
  - a workspace member's `requires-python` differs from the root's;
  - the root's bound isn't of the form `>=3.X,<3.Y`;
  - the Python versions in `.github/workflows/ci.yml`'s matrix aren't exactly the minor versions the bound allows;
  - `.python-version` isn't the lowest of them;
  - ruff's `target-version` or mypy's `python_version` isn't the lowest of them. These two already say 3.12, and
    they have to move when 3.12 is dropped, so the same check covers them.
- **Docs.** The README's Development section says which versions are supported, that uv refuses others, and how to
  test a version other than the default.
- **BREAKING** (for anyone running troupe from source on 3.14 or later): uv now refuses that interpreter instead of
  using it. No release has been published, so no installed copy is affected.

## Capabilities

### New Capabilities

- `python-support`: which Python versions troupe supports, how that's declared and enforced, and how the
  declaration stays in step with what CI tests.

### Modified Capabilities

None.

## Impact

- **Files:** the nine `pyproject.toml` files, `uv.lock`, a new `.python-version`, new `scripts/python_versions.py`
  and `scripts/on.py` with their tests in `scripts/tests/`, `.gitignore` (for `.venvs/`), and `README.md`.
  `.github/workflows/ci.yml` isn't changed. The check reads it.
- **Developers:** an existing `.venv` built on 3.14 or later is replaced by uv with a 3.12 one on the next
  `uv run` or `uv sync`. uv installs 3.12 if it's missing.
- **CI:** no new jobs. `setup-uv`'s `python-version` input sets `UV_PYTHON`, which takes precedence over
  `.python-version`, so the 3.13 jobs still run on 3.13.
- **Issues:** the pull request closes #105, the sub-issue for Part 1. #104 stays open until Part 2's sub-issue
  closes too. troupe-run/infrastructure#43 waits on Part 2.
