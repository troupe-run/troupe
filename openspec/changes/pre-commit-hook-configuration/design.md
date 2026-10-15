# Design

## Context

The guard and its pytest plugin are already in troupe, delivered from troupe-run/infrastructure:
- `scripts/guard.py` has `check_paths` (parse and validate), `check_scope` (the decision), `marker_expression`, and
  `commit_checks`. `commit_checks` reads the *staged* `scripts/check-paths.toml` and runs `uv run scripts/check.py
  [--scope <name> ...]`.
- `scripts/guard_pytest.py` registers each declared scope as a marker, records the repository files each test
  opens, and fails a test whose reads contradict its tags.

Neither is used yet. troupe has no declaration, its `check.py` takes no arguments, and pytest doesn't load the
plugin. Both files are delivered, so this change can't edit them. The guard refuses a commit that does.

The infrastructure change's design (`commit-check-paths`, archived 2026-10-15) defines the contract this change
implements: D1 and D2 for the declaration, D8 for `--scope`, and D9 for the tags. infrastructure's own
`scripts/check.py` is the reference implementation of D8.

What troupe's tests read (checked on `main` at `ce644b1`):
- No test reads `openspec/`.
- Six modules in `packages/troupe/tests/` read `docs/` at module level (`DOC = ... / "docs" / ...`) and compare it
  with the code: `test_cli_docs`, `test_runs_doc`, `test_runners_doc`, `test_event_store_doc`,
  `test_exit_codes_doc`, `test_platform_docs`. They call `main()` in-process, so the plugin sees their reads.
- `plugins/runner-scripted/tests/test_scripted_schemas.py` has one test that reads the scripted runner's README.
- No test reads the root `README.md`.

## Goals / Non-Goals

**Goals:**
- troupe's `check.py --scope` behaves exactly like infrastructure's, so the guard's contract has one meaning.
- The list of `docs` tests comes from the plugin's findings, not from a grep.
- Nothing changes for a run without `--scope`, apart from the plugin's check.

**Non-Goals:**
- Editing `guard.py` or `guard_pytest.py`. A gap in them is fixed in troupe-run/infrastructure and delivered.
- CI's use of `check-scope` (#101) and package scopes (#109).
- Skipping the root `README.md`. No test reads it, so it could go in `[skip]`, and the plugin would keep that true.
  But #108 keeps it in no group, and it changes rarely (1 commit in 228). It can be added later in one line.

## Decisions

### D1. `check.py` follows infrastructure's reference shape

`check.py` gets the same parts as infrastructure's:
- `argparse`, with `--scope` as `action="append"`;
- `requested_scopes(names, declaration)`, which exits naming any undeclared scope, then returns the names sorted and
  deduplicated;
- `gates(scopes)`, which builds the gate list and adds `-m <guard.marker_expression(scopes)>` to pytest when scopes
  are given;
- `run_gates`, which treats pytest's exit 5 as a pass only in a scoped run, and prints that nothing was tagged.

The declaration is read and validated only when `--scope` is given, from the working tree, with
`guard.read_working_tree`. A malformed one exits with the guard's own message (`CheckPathsError.decision().text()`).
Plain `check.py` doesn't read the declaration: the plugin validates it in the tests gate anyway, and the full check
has no use for it.

Today `GATES` is a module-level list, built when the module is imported. It becomes a function so the pytest command
can depend on the scopes. `scripts/tests/test_check_activation.py` imports `check` and calls only
`activate_git_hooks`, so it is unaffected. `import guard` moves to the top of the module, as in infrastructure,
because `--scope` needs it whether or not the directory is a git checkout.

*Alternative:* write troupe's own version. Rejected, because two implementations of one contract drift. Keeping the
same function names also makes the two files easy to compare.

### D2. Tags: `pytestmark` per module, a mark per test otherwise

The six doc modules get `pytestmark = pytest.mark.docs`. Their docs are read at module level, so the plugin
attributes the read to every test in the module, and every one of them needs the tag. The scripted README test gets
`@pytest.mark.docs` on its own, because its module's other tests read schemas, not the README.

*Alternative:* tag by directory with a conftest hook. There's no directory of only doc tests, so this doesn't fit.
#109 takes up directory tagging for package scopes.

### D3. The plugin finds the list

The declaration and the plugin go in first, with no tags. Then a full run lists every test that reads `docs/**`
untagged, and those tests get the tag. The list in the Context is what's expected. If the run finds more, they're
tagged too and recorded in the tasks. So the final list is checked, not assumed. The run also confirms that no test
reads `openspec/`.

### D4. The plugin is loaded from `addopts`, with `scripts` on `pythonpath`

```toml
pythonpath = ["packages/troupe/tests", "scripts"]
addopts = ["-ra", "--strict-markers", "--strict-config", "-p", "protocol_guard", "-p", "guard_pytest"]
```

This is how `protocol_guard` is already loaded. Putting `scripts` on `pythonpath` makes `check`, `guard`, `on`,
`python_versions` and `release_config` importable by those names in every test. A test module, or a module on the
existing `pythonpath`, with one of those names would now collide. The tasks check that none exists, and
`scripts/tests/conftest.py` already puts `scripts` first on `sys.path`, so its tests are unaffected.

### D5. Verified on real commits

The commits that make this change are the evidence:
- once the declaration is on the branch, a task-tick commit staging only `openspec/` shows the guard skipping the
  check;
- a commit staging only the README's docs change shows `--scope docs`;
- the commits that change code run the full check, plugin included.

The guard reads the *staged* declaration, and a commit that stages `scripts/check-paths.toml` always runs the full
check (guard design D4). So the declaration's own commit runs the full check, and later commits use it.

## Risks / Trade-offs

- [The plugin's first runs on macOS and Windows in troupe] → infrastructure's CI proved it, but troupe's suite opens
  far more files (event stores, theatres). → The full check runs locally before the first commit, and the PR needs
  all six CI jobs green.
- [The audit hook slows the suite] → It resolves a path and compares strings for each open while a test runs. →
  Measure the full suite with and without the plugin, on the same machine, and record both times in the tasks. If the
  plugin adds more than about 5%, stop and raise it in infrastructure before merging.
- [A doc test that reads through a subprocess] → The plugin can't see it, so it would go untagged and a docs-only
  commit would skip it. → All seven read in-process today. The comment in `check-paths.toml` says a `docs` test must
  read in-process, or be tagged by hand.
- [A docs-only commit misses a broken link to code] → The doc tests run under `--scope docs`, and they're what
  checks docs against code. Pushes to `main`, and every code commit, still run everything.
- [`scripts` on `pythonpath` shadows a name] → Checked in the tasks (D4).

## Migration Plan

1. Land on this branch in order: `check.py --scope` with its tests; the declaration and the plugin; the tags the
   plugin finds; then the README.
2. Once merged, every troupe commit uses it. Nothing else needs to change. infrastructure already knows troupe's
   declaration is coming (its design D7).
3. Rollback: delete `scripts/check-paths.toml`. Commits then run the full check, and the plugin registers no
   markers and checks nothing. Remove `-p guard_pytest` too to drop the audit hook.
