# Proposal

## Why

Every commit runs the full `scripts/check.py`, about 230 seconds locally, even when it changes nothing a test reads.
The commit guard, delivered from troupe-run/infrastructure (#48, change `commit-check-paths`), can already skip the
check or narrow it, but only from a repository's own `scripts/check-paths.toml`. troupe has no declaration, so the
guard runs everything. Of the 228 commits on `main` since 1 October, 92 (40%) touched only `openspec/**`: archives,
task ticks and evidence. Issue #108 asks troupe to adopt the selective check so those commits skip it, and so that
docs-only commits run only the tests that read the docs.

This change is all of #108. Package-level scopes for code are #109, which follows. CI's use of the same declaration
(`guard.py check-scope`) is #101, which depends on this change.

## What Changes

- **A declaration.** A new `scripts/check-paths.toml` skips `openspec/**` and declares one scope, `docs`, covering
  `docs/**` and `plugins/runner-scripted/README.md`. Every other path, including the root `README.md`, still runs
  the full check.
- **`check.py --scope <name>`,** repeatable. Every gate still runs (ruff, mypy, import contracts), and only the tests
  narrow, to those tagged with any of the scopes. A scope the declaration doesn't list is refused before any gate
  runs. In a scoped run, "no tests ran" passes and says there was nothing to test. This follows the contract in the
  guard's design D8. Plain `uv run scripts/check.py` is unchanged.
- **Tags on the doc tests.** The tests that check documentation against the code are tagged `docs`: the six
  `test_*_doc*.py` modules in `packages/troupe/tests/`, and the README test in `plugins/runner-scripted/tests/`.
  The plugin, below, decides the final list. Any test it finds reading `docs/**` untagged gets the tag.
- **Every test run checks the tags.** pytest loads the delivered `guard_pytest` plugin, with `scripts` on its
  `pythonpath`. A test that reads a `docs` path without the tag, or reads anything under `openspec/`, fails and is
  named. This keeps the declaration true as tests change.
- **Docs.** The README's Development section says what a commit runs, and how to run a scope by hand.

Nothing changes for code commits: they run the full check as before.

## Capabilities

### New Capabilities
- `quality-check`: what `scripts/check.py` runs, the scoped form of it, and troupe's declaration of which paths need
  which part of it. It also covers the guarantee that every test run keeps that declaration honest.

### Modified Capabilities

None. The commit guard's behaviour is specified in troupe-run/infrastructure (`development-workflow`) and doesn't
change. This change supplies the repository's side of it.

## Impact

- New: `scripts/check-paths.toml`.
- Changed: `scripts/check.py` (argument parsing, scope validation, narrowed pytest, exit 5), `pyproject.toml`
  (`[tool.pytest.ini_options]`: `-p guard_pytest` in `addopts`, `scripts` in `pythonpath`), the doc test modules
  (a `pytestmark`), `README.md`.
- Unchanged, and not edited here: `scripts/guard.py` and `scripts/guard_pytest.py`. They're delivered, and the
  guard refuses commits that change them.
- Every test run gains an audit hook. The infrastructure dry run measured no added time, and this change measures it
  again on troupe.
- Rollback: delete `scripts/check-paths.toml`. Commits then run the full check, and the plugin checks nothing.
