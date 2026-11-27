# Design

## Context

Hypothesis's default database is `DirectoryBasedExampleDatabase(storage_directory("examples"))`. Its storage
directory is `HYPOTHESIS_STORAGE_DIRECTORY` when set, otherwise `.hypothesis` under the current directory, worked out
when Hypothesis is imported. pytest reads the root `pyproject.toml` from any directory in the repository, so its
`addopts` load `hypothesis_profiles` (from `packages/troupe/tests`, on the configured `pythonpath`) in every run: the
check, a direct `pytest` from the root or a package, the flake hunt and mutation runs. That plugin already re-registers
`default` (no deadline, #100).

## Goals / Non-Goals

**Goals:** one example database per repository checkout for every run on the `default` profile; the flake hunt's
private databases keep working.

**Non-Goals:**
- Clearing, moving or merging existing `.hypothesis/` directories. They're left alone; old examples in
  `packages/troupe/.hypothesis/` stop being replayed. Their bugs were fixed when found (#532 is merged).
- infrastructure's tests (troupe-run/infrastructure#421).
- The `ci` profile: CI keeps fixed seeds and no database.

## Decisions

- **D1: set the database in the `default` profile, in `hypothesis_profiles.py`.** It's the one plugin every run
  loads, and it already owns the profile. The database is
  `DirectoryBasedExampleDatabase(<repository root>/.hypothesis/examples)`, the root found from the plugin's own path
  (`packages/troupe/tests/hypothesis_profiles.py`, three directories up), so it doesn't depend on the current
  directory. In mutmut's copy of the tree the root is that copy, which is where those runs keep it today.
  - *Alternative: a root `conftest.py`.* It loads only when the root is collected or is the `confcutdir`; a run of
    `packages/troupe/tests` started from there wouldn't reach it. The plugin is loaded through `addopts` regardless.
  - *Alternative: `hypothesis.configuration.set_hypothesis_home_dir`.* It moves every Hypothesis cache, but it isn't
    public API. The settings `database` is.
  - *Alternative: set `HYPOTHESIS_STORAGE_DIRECTORY` in `os.environ`.* Every child process the tests start would
    inherit it, changing their Hypothesis runs as a side effect.
- **D2: an environment storage directory wins.** When `HYPOTHESIS_STORAGE_DIRECTORY` is set (and not empty, as
  Hypothesis reads it), the profile leaves the database at Hypothesis's own default, which then uses that directory.
  The flake hunt relies on this for its private per-round databases (spec: flake-hunt), and the profile tests' child
  runs set it to stay in their temp directory.
- **D3: test it end to end in a copy of the layout.** The integration test builds a repository in a temp directory:
  the plugin copied to `packages/troupe/tests/`, a `pytest.ini` at its root loading it, and a property that fails for
  any number of 1000 or more. One run finds and saves the failure; a second, from another directory, runs only
  Hypothesis's reuse phase, so it fails only if it reads the saved example. Neither run touches the real repository's
  database. Run against main's plugin, both direction tests fail (the replay run finds an empty database and passes).

## Risks / Trade-offs

- **A saved example now fails every run in the checkout, including the commit check, until its bug is fixed.** That's
  the point (#537), and it's what the guard's memory note already expects from the root.
- **The plugin's root is found by path depth.** Moving the plugin would point the database elsewhere. A unit test
  checks the database path is the directory holding the root `pyproject.toml`.
