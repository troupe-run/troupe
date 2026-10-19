# Proposal: CI runs only the check a pull request's paths need

## Why

Every pull request runs the full `scripts/check.py` on all 12 required legs (Linux, macOS and Windows, Python 3.12
to 3.15), whatever it changes (#101). A pull request whose only changes are archive commits, task ticks or evidence
still costs the full suite on every leg. Each of those runs is another chance for an unrelated timing flake to fail
it, as one did on #99, in store-text on Windows 3.13. The commit guard already skips or narrows the check by path
(#108, #111, #116). CI doesn't ask yet.

## What Changes

- **A `changes` job** works out the pull request's changed paths (`git diff --name-only --no-renames
  "$BASE...$HEAD"`) and pipes them to `guard.py check-scope`, which answers `scope=none|full|<a>,<b>` and
  `check-args`. It reads troupe's `scripts/check-paths.toml`, so troupe keeps one copy of the rule, and this change
  adds no second reader.
- **The 12 legs** need `changes`. They're skipped when it answers `none`. They run `check.py` with its `check-args`
  for a scoped answer, and the full check otherwise. A failed `changes` job, or one that can't work out the paths,
  gives no answer, and no answer means the full check.
- **One required `check` job** reports for the legs. GitHub reports a skipped matrix job under its unexpanded name
  (`check (${{ matrix.os }}, …)`, proven in troupe-run/infrastructure's `run-checks-by-path`, task 1.1), so the 12
  per-leg required checks would wait forever on a pull request that skipped them. `check` passes when every leg
  passed, or when they were all skipped because `changes` answered `none`. It fails on anything else.
- **The required checks change in troupe-run/infrastructure.** `tofu/required-checks.json` lists `check` for troupe
  instead of the 12 legs. That's infrastructure's file, so it gets its own issue and pull request, merged and applied
  after this one (design D7).
- **`main` keeps everything.** A push to `main` runs no `changes` job, so every leg runs the full check.
- **ruff stops reading `openspec/`.** `ruff format --check .` formats the Python blocks in Markdown, and today it
  reads every file under `openspec/`. That contradicts the skip list's comment that no gate reads them. With CI
  skipping `openspec/`-only pull requests, a badly formatted block there would first fail `main`. `pyproject.toml`
  excludes `openspec` from ruff.
- **`guard` is unchanged** and keeps running on every push.

Out of scope:

- **The commit guard and `check-scope`.** They're delivered from troupe-run/infrastructure and already do what's
  needed. Nothing delivered changes.
- **The declaration's groups.** Which paths are skipped or scoped stays as #108 and #116 left it. A docs-only pull
  request runs `--scope docs` (every gate, and the 26 tests tagged `docs`) on every leg.
- **Narrowing the legs** to the platforms or Python versions a change needs. It's all of them or none.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `quality-check`: new requirements for CI. A pull request's legs run only what its paths need, `main` and an
  unknown answer run the full check, and one `check` result reports for the legs. And a new requirement that no
  gate reads `openspec/`, which the skip list already depends on and ruff breaks today.

`python-support` needs no change: the matrix still lists exactly the supported versions, and
`scripts/python_versions.py` still reads it.

## Impact

- `.github/workflows/ci.yml`: the `changes` job, the legs' `needs` and `if`, the scoped `check.py` call, and the
  `check` result job.
- A new `scripts/check_result.py` (standard library only, run with the runner's `python3`) that judges the legs'
  result, with its tests in `scripts/tests/`, and its entry in `scopes.scripts` in `scripts/check-paths.toml`.
- `pyproject.toml`: ruff's `extend-exclude`. A test shows a badly formatted block under `openspec/` no longer fails
  the format gate, while the same block under `docs/` still does.
- `README.md`: what CI runs, and which check is required.
- troupe-run/infrastructure: a new issue and pull request changing troupe's entry in `tofu/required-checks.json`
  from 12 contexts to `check`. Its plan updates troupe's ruleset, and the owner approves the apply.
