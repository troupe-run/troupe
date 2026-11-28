# Tasks

## 1. The failure, reproduced

- [x] 1.1 Reproduce #543 in a container with infrastructure main's `mutation_run.py`, troupe checked out under
  `target/` and the troupe unit narrowed to `unit/test_hypothesis_profiles_unit.py`. Verify: on main the baseline fails
  with `target/.hypothesis/examples == target/packages/.hypothesis/examples`.

## 2. The layout test, failing first

- [x] 2.1 Add the integration test (design D2) to `packages/troupe/tests/integration/test_hypothesis_profiles.py`:
  the unit test run in a copy of the repository under `tmp_path/target`, from the root, from `packages/troupe`, and
  from a mutmut-shaped copy with the checkout's entries linked. Verify: against main's unit test the mutmut-shaped case
  fails with #543's assertion, and the root and package cases pass.

## 3. The fix

- [x] 3.1 In `unit/test_hypothesis_profiles_unit.py`, take the root from `pytestconfig.inipath`, resolved (design D1).
  Verify: the three layout cases pass, and the unit test passes run from the root and from `packages/troupe`.
- [x] 3.2 Rerun 1.1's container reproduction on the fixed branch. Verify: the baseline passes and mutmut goes on to
  test mutants.
- [x] 3.3 `uv run scripts/check.py` passes.

## Workflow follow-up

- Draft PR closing #543; act on Claude's review; archive on the branch; the owner merges.
- After the merge, ask the owner to dispatch infrastructure's `mutation.yml` for troupe and check it gets past the
  baseline.
