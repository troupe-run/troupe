# Proposal

## Why

troupe#543: since #538 (one Hypothesis example database), every nightly mutation run of troupe has failed its baseline
(infrastructure runs 45993904924 and 46001639787). `test_every_run_shares_the_roots_example_database` expects
`target/packages/.hypothesis/examples`, while the database lookup gives `target/.hypothesis/examples`. mutmut stops
before testing any mutant, so the night gives no scores, and infrastructure#418's re-score is blocked.

The run checks troupe out under `target/` and runs the unit tests from mutmut's copy,
`packages/troupe/mutants/tests`. infrastructure's `mutation_run.py` (`link_checkout_entries`) links every entry of the
checkout into `packages/`, so that tests counting directories up from the copy still find what they read. One of those
links is `packages/pyproject.toml` → `../pyproject.toml`. The test finds "the repository root" by walking up from its
own file to the first `pyproject.toml` with pytest's configuration, and stops at that link, one directory too low. The
lookup resolves its own path, finds the real root, and is right: it's where the run's other tests and the lookup's own
design put the database. Reproduced in a container with infrastructure main's `mutation_run.py`, the troupe unit
narrowed to that test file: the same assertion fails.

## What Changes

- The unit test takes the repository root from the configuration file pytest is actually using
  (`pytestconfig.inipath`), with links resolved. In the mutation run that's the linked `packages/pyproject.toml`, which
  resolves to the root's. The lookup is unchanged.
- A new integration test, written first and failing on main, runs that unit test in copies of the repository's layout
  under a temp directory, so each is a checkout under another directory. It runs from the root, from
  `packages/troupe`, and from a mutmut-shaped copy: the tests copied to `packages/troupe/mutants/tests`, and the
  checkout's entries linked into `packages/` and `packages/troupe/` as `mutation_run.py` links them. It checks that
  the lookup and the test agree in each. Where the platform can't make symbolic links (Windows without the privilege),
  the mutmut-shaped case is skipped, as the clone tests skip theirs.
- The `quality-check` requirement "Every test run shares one Hypothesis example database" gains a scenario for a
  checkout under another directory, run from a mutation tool's copy.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `quality-check`: "Every test run shares one Hypothesis example database" gains a scenario for a run from a mutation
  tool's copy of a checkout under another directory.

## Impact

- `packages/troupe/tests/unit/test_hypothesis_profiles_unit.py` (the test's root).
- `packages/troupe/tests/integration/test_hypothesis_profiles.py` (the layout test).
- No change to `hypothesis_profiles.py`, no code under `src/`, no protocol or schema change.
- infrastructure is unchanged: its layout is the one being supported. After the merge, a dispatch of `mutation.yml`
  for troupe should get past the baseline.
