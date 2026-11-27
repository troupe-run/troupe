# Tasks

## 1. Test first

- [x] 1.1 In `integration/test_hypothesis_profiles.py`, build a copy of the layout and check a failure saved from
  `packages/troupe` fails a replay-only run from the root, and the reverse (design D3). Verify: both fail on main.
- [x] 1.2 Check that `HYPOTHESIS_STORAGE_DIRECTORY` keeps the examples in that directory and out of the repository's
  database. Verify: it passes on main (the behaviour to keep).

## 2. Fix

- [x] 2.1 In `hypothesis_profiles.py`, give `default` the database `<root>/.hypothesis/examples` unless
  `HYPOTHESIS_STORAGE_DIRECTORY` is set (design D1, D2). Verify: the tests in 1.1 and 1.2 pass.
- [x] 2.2 A unit test checks the database the plugin chooses is the root's `.hypothesis/examples` (the directory
  holding the root `pyproject.toml`), and none when the environment sets a storage directory; `ci` still has none.
  Verify: the unit tests fail when `shared_database` returns None, and the integration tests fail when the profile is
  registered without its database.
- [x] 2.3 Run the plugin's tests from the root and from `packages/troupe`. Verify: both pass, and no `.hypothesis/`
  directory was cleared.
- [x] 2.4 `uv run scripts/check.py` passes.

## Workflow follow-up

- Draft PR closing #537; act on the review; mark ready; archive; owner merges.
