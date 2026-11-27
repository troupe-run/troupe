# Proposal

## Why

troupe#537: Hypothesis saves the examples it found failing in `.hypothesis/` under the current directory, and replays
them first next time. `scripts/check.py`, and so the guard's commit check, runs pytest from the repository root, while
a developer or worker often runs it from `packages/troupe`. On 2026-11-27 a property test found a real bug (#532) from
`packages/troupe`. The full check never replayed the failing example, passed every gate and let the commit through. A
failure Hypothesis has found must fail every later run, wherever pytest is started.

## What Changes

- The project's Hypothesis plugin (`packages/troupe/tests/hypothesis_profiles.py`, loaded for every test path through
  the root's `addopts`) gives the `default` profile one example database for the repository,
  `<repository root>/.hypothesis/examples`, whatever the current directory.
- `HYPOTHESIS_STORAGE_DIRECTORY`, when set, still decides where examples go: the flake hunt gives each round a private
  database that way and keeps out of the repository's. The `ci` profile keeps no database.
- Tests, written first and failing on main: a failure saved from a package directory fails a replay-only run from the
  root, and one saved from the root fails a run from the package directory. A third, passing on main and after, shows
  the environment's storage directory keeps examples out of the repository.
- Existing `.hypothesis/` directories are left as they are. Examples saved under `packages/troupe/.hypothesis/` before
  this change aren't replayed after it; nothing is deleted or moved.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `quality-check`: a new requirement, "Every test run shares one Hypothesis example database", with scenarios for a
  failure found from another directory and for an environment-chosen storage directory.

## Impact

- `packages/troupe/tests/hypothesis_profiles.py` (the profile).
- `packages/troupe/tests/integration/test_hypothesis_profiles.py`, `unit/test_hypothesis_profiles_unit.py` (tests).
- No code under `src/`, no protocol or schema change.
- infrastructure's tests have the same gap; raised as troupe-run/infrastructure#421, not fixed here.
