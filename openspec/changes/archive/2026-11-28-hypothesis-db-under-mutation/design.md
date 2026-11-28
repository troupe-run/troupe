# Design

## Context

See proposal.md, "Why", for the failure. The run's layout, from infrastructure's `mutation.yml` and
`scripts/mutation_run.py`: the checkout is `target/`, mutmut works in `target/packages/troupe` and runs the tests from
its copy, `packages/troupe/mutants/tests`. `link_checkout_entries` links each checkout entry into `packages/` (and
each `packages/` entry into `packages/troupe/`, where the name is free), `.git` excepted. pytest's rootdir comes out as
`target/packages` (its `pyproject.toml` is the linked root one), so the configured `pythonpath` entry
`packages/troupe/tests` is `target/packages/packages/troupe/tests`, which the links lead back to the real
`packages/troupe/tests`. The plugin loads from there and resolves its own path, so the lookup's root is `target`.

one-hypothesis-database's design D1 expected "in mutmut's copy of the tree the root is that copy". It isn't: the
plugin is loaded from the checkout, and the run shares the checkout's database. That's harmless (the run's tests write
to the checkout, which is thrown away) and it's what this change keeps.

## Goals / Non-Goals

**Goals:** the lookup and its test agree in every layout troupe's tests run in: the repository root, `packages/troupe`,
a checkout under another directory, and mutmut's copy as infrastructure lays it out.

**Non-Goals:**
- Changing infrastructure's layout or its links: other tests rely on them (#343, quality-scope design D5).
- Changing where the mutation run's database goes.

## Decisions

- **D1: fix the test, not the lookup.** The lookup already finds the real root in every layout; the test's own idea of
  the root is what's fooled. The test takes the root from `pytestconfig.inipath`, resolved: the configuration file this
  run actually uses, which is the root's `pyproject.toml` from the root and from `packages/troupe`, and a link to it in
  mutmut's copy. That's an independent check: it doesn't count directories from the plugin as the lookup does.
  - *Alternative: keep the walk up from the test's file, resolving each `pyproject.toml` found.* It works too, but it
    is a second hand-written root search that can drift from what pytest reads.
  - *Alternative: make the lookup search upwards for the configuration.* It would change behaviour that isn't broken,
    and in mutmut's copy it would find the same root it finds now.
- **D2: test it by running the unit test in copies of the layout.** An integration test builds a repository under
  `tmp_path/target` (a checkout under another directory): a root `pyproject.toml` holding pytest's configuration
  (`pythonpath` and `addopts` loading the plugin, as the real one does), the plugin and the unit test copied to their
  places in `packages/troupe/tests`. It runs that unit test from the root and from `packages/troupe`. For mutmut's
  copy it copies the tests to `packages/troupe/mutants/tests`, links the checkout's entries into `packages/` and
  `packages/troupe/` the way `link_checkout_entries` does, and runs the copy from `packages/troupe/mutants`, as mutmut
  does. Each run must pass. Against main's unit test the mutmut-shaped run fails with #543's assertion. The case
  needing links is skipped where the account can't make them, as `test_platform_clones.py` does.
  - *Alternative: run mutmut in the test.* Too slow and heavy for the suite. The container reproduction (task 1.1)
    checks the real run once.

## Risks / Trade-offs

- [infrastructure changes its layout again] → The integration test copies today's layout. A different layout could
  break the test again without breaking this one. The nightly run's baseline would show it, as it did here.
- [Windows can't make the links] → that case is skipped there. mutmut runs only on Linux in the workflow, where it
  always runs.
