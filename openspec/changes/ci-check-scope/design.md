# Design: CI runs only the check a pull request's paths need

## Context

See proposal.md for why. What exists today:

- `.github/workflows/ci.yml` has one job, `check`, a 3 × 4 matrix (`ubuntu-latest`, `macos-latest`,
  `windows-latest` × Python 3.12 to 3.15) that runs `uv sync --locked` and then `uv run scripts/check.py`. It runs on
  `pull_request` and on `push` to `main`. All 12 contexts, `check (<os>, Python <v>)`, are required by troupe's
  ruleset, which troupe-run/infrastructure's `tofu/required-checks.json` declares (decision #17).
- `scripts/check-paths.toml` skips `openspec/**`, and declares `docs`, seven package scopes and `scripts`. The commit
  guard reads it before every commit.
- `scripts/guard.py check-scope` (delivered, not troupe's) reads the changed paths on stdin and the declaration from
  the working tree. It prints `scope=none|full|<a>,<b>` and `check-args=--scope <a> --scope <b>` (empty for `full`
  and `none`). No paths, or a changed declaration, answers `full`. A malformed declaration exits 1 and prints nothing
  on stdout (commit-check-paths D6).
- `scripts/python_versions.py` reads the matrix's `python: [...]` line in `ci.yml`, and fails the check if it
  disagrees with the supported versions.
- troupe-run/infrastructure did the same for its own CI in `run-checks-by-path` (#78 there). Its task 1.1 proved on a
  throwaway repository that a matrix job skipped by its job-level `if` reports one check run under its unexpanded
  name, and that a result job with `if: always()` can stand in for the legs as the required check. This design copies
  that shape.
- `ruff format --check .` formats the Python blocks in Markdown. It reads 326 files under `openspec/` today (`ruff
  format --check -v .`), and a badly formatted block in `docs/a.md` fails it (checked in a scratch tree with troupe's
  `pyproject.toml`).

## Goals / Non-Goals

**Goals:**
- Every required check reports on every pull request, whether the legs run or not.
- An unknown answer runs everything, and so does every push to `main`.
- One copy of the path rule: CI asks `check-scope`, and reads nothing else from the declaration.

**Non-Goals:**
- Changing `guard.yml`, `check-scope` or any delivered file.
- Skipping the jobs that are already cheap (`guard`, `release`).
- Saving the legs' runners on a full run. `changes` adds one short job before them (see Risks).

## Decisions

### D1. A `changes` job asks `check-scope`, on pull requests only

```yaml
changes:
  name: what does it need?
  if: github.event_name == 'pull_request'
  runs-on: ubuntu-latest
  outputs:
    scope: ${{ steps.paths.outputs.scope }}
    check-args: ${{ steps.paths.outputs['check-args'] }}
  steps:
    - checkout, fetch-depth: 0, ref: the pull request's head sha
    - setup-uv
    - id: paths
      env: { BASE: <pull_request.base.sha>, HEAD: <pull_request.head.sha> }
      run: |
        git diff --name-only --no-renames "$BASE...$HEAD" > "$RUNNER_TEMP/paths"
        uv run --no-project scripts/guard.py check-scope < "$RUNNER_TEMP/paths" >> "$GITHUB_OUTPUT"
```

This is the entry the guard's design gave CI (commit-check-paths D6), and infrastructure's `changes` job, less its
`guard_tests_needed.py` line. The three-dot diff is from the merge base, so commits on `main` since the branch forked
aren't counted as the pull request's. `--no-renames` lists both sides of a rename, as the commit hook does. `bash`
runs every step here: it's on Linux. `set -e` (the default for `run`) fails the step if `git diff` fails.

How each way of not knowing the paths ends:

- **`git diff` fails** (a base sha missing from the clone): the step fails, `changes` fails, and its outputs are
  empty. The legs run with no `check-args`, which is the full check (D2).
- **`git diff` lists nothing** (a pull request with no file changes): `check-scope` answers `full`.
- **A malformed declaration**: `check-scope` exits 1, `changes` fails, and the legs run the full check. That fails at
  `guard_pytest`'s session start, naming the file. The pull request is blocked either way.
- **A force push** changes the head sha, and the new event carries it. The base is still the pull request's base, so
  the diff is still the whole pull request.

*Alternatives:* `paths-ignore` on the workflow (a workflow that never starts reports no check, and required checks
wait forever); deciding in each leg (12 runners, macOS and Windows among them, each starting up to do nothing, and 12
copies of the decision); `dorny/paths-filter` or similar (a second copy of the rule, which #101 rules out).

### D2. The legs need `changes`, skip on `none`, and run the check with its `check-args`

```yaml
check-legs:
  name: check (${{ matrix.os }}, Python ${{ matrix.python }})
  needs: changes
  if: ${{ !cancelled() && needs.changes.outputs.scope != 'none' }}
  ...
  - name: Check (the same script as local runs)
    shell: bash
    env: { CHECK_ARGS: "${{ needs.changes.outputs['check-args'] }}" }
    run: uv run scripts/check.py $CHECK_ARGS
```

- **`!cancelled()`** lets the legs run when `changes` failed or was skipped. Without it, a failed `needs` skips the
  legs, which here would mean nothing tests the pull request. A skipped `changes` (a push to `main`) gives empty
  outputs, `''` isn't `'none'`, and the legs run in full (D5).
- **Only `none` skips.** Any other value, including empty and `full`, runs the legs, so an answer the workflow
  doesn't recognise runs more, never less.
- **`$CHECK_ARGS` is unquoted on purpose.** It's `--scope <a> --scope <b>` words, and scope names match
  `[a-z][a-z0-9_]*`, so splitting on spaces is safe. It's empty for the full check.
- **`shell: bash` on that step**, because the Windows runner's default shell is PowerShell, which would pass
  `--scope docs` as one argument. Git Bash is on every Windows runner. The other steps keep their default shell.
- **The legs keep their names**, so their history and the flake records that name them stay readable. The job's id
  changes from `check` to `check-legs`, because `check` becomes the result job's name (D3). Ids aren't shown.
- **The matrix line is unchanged**, so `python_versions.py` keeps reading it.

### D3. A `check` result job reports for the legs

```yaml
check:
  name: check
  needs: [changes, check-legs]
  if: ${{ always() }}
  runs-on: ubuntu-latest
  steps:
    - checkout (no fetch-depth needed)
    - env: { LEGS: <needs.check-legs.result>, CHANGES: <needs.changes.result>, SCOPE: <needs.changes.outputs.scope> }
      run: python3 scripts/check_result.py "$LEGS" "$CHANGES" "$SCOPE"
```

`always()`, not `!cancelled()`, so it reports even when the run is cancelled, and fails then. A matrix job's
`result` is `success` only when every leg succeeded, `failure` when any failed, and `cancelled` or `skipped`
otherwise. `scripts/check_result.py` passes on:

| `check-legs` | `changes` | `scope` | `check` |
|---|---|---|---|
| `success` | any | any | passes |
| `skipped` | `success` | `none` | passes, saying no path needed the check |
| `skipped` | anything else | anything else | fails: skipped without a reason to skip |
| `failure`, `cancelled` | any | any | fails, naming the result |
| anything else | any | any | fails, naming the value it doesn't know |

It's a script, not inline shell, so the table has a test per row, including the unknown value. It's standard library
only, and runs with the runner's `python3` before anything is installed, as `guard.py check-scope` does with `uv run
--no-project`. It's troupe's own file. It doesn't read the declaration, so it isn't a second copy of the rule.

The script goes in `scopes.scripts` in `scripts/check-paths.toml` by its exact path, with its tests under
`scripts/tests/`, so a change to it alone runs the scripts suite. A change to `ci.yml` is in no scope and runs the full
check, and a pull request that changes `check_result.py` runs the new result job on itself.

*Alternative:* the legs as the required checks, each skipping its steps (the option the owner turned down: 12
runner starts per pull request, and the decision made 12 times).

### D4. ruff excludes `openspec`

`pyproject.toml` gets `extend-exclude = ["openspec"]` under `[tool.ruff]`. That makes the skip list's comment ("No
gate reads these") true for ruff, the one gate that broke it. mypy reads its `files` list, the import contracts read
the packages, and pytest is kept off `openspec/` by `guard_pytest`. Formatting the code in a design is worth nothing
to anyone. Infrastructure made the same change for the same reason (`run-checks-by-path` D9).

A test in `scripts/tests/` copies the repository's `pyproject.toml` into a temporary tree, writes one badly formatted
Python block to `openspec/changes/x/design.md` and the same block to `docs/x.md`, and runs `ruff format --check .`
there. It expects the run to name `docs/x.md` and not the `openspec/` file. The `docs/` half is what proves the test
can fail. It reads `pyproject.toml`, which is in no scope, so it needs no tag.

*Alternative:* taking `openspec/**` out of skip (every planning commit would run the full check again, the cost the
skip list exists to remove).

### D5. `main` runs everything

On `push` to `main`, `changes` is skipped, `scope` is empty, and every leg runs the full check. `check` passes on
their `success`. `main` doesn't require a branch to be up to date, so its merged tree may be one no pull request
tested. A full run also catches what a scoped one can't: a test that reads a scoped path without its tag fails only on
a run that includes the test.

### D6. Proving it before the merge, on a throwaway repository

The done-when needs a pull request that changes only `openspec/**` and passes every required check without running
the tests. This pull request can't show that: it changes `ci.yml`, so it runs the full check on itself. A probe branch
in troupe would be refused by the guard (no OpenSpec change of its own), and the ruleset can't require `check` until
D7.

So the evidence task pushes this branch to a throwaway repository, `troupe-run/troupe-probe-ci-check-scope`, with a
ruleset requiring `check` and `guard (workflow rules)` off, and opens three pull requests there against it:
`openspec/`-only (legs skipped, `check` passes), `docs/`-only (12 legs run `--scope docs`), and core code (12 legs run
the full check). The run links go in tasks.md and the pull request, and the repository is deleted after. The repo is
created and deleted only with the owner's go-ahead, as infrastructure's probe was.

### D7. troupe's required checks change in infrastructure, after this merges

troupe-run/infrastructure's `tofu/required-checks.json` lists troupe's 12 contexts. It must list `check` instead. The
order matters:

1. **This pull request merges first.** Its own run reports all 12 legs (it changes `ci.yml`, so it runs the full
   check), which satisfies the old ruleset, and it adds the `check` job.
2. **Then infrastructure's pull request** changes troupe's entry to `check`. Its plan updates troupe's ruleset, and
   the owner approves the apply.

The other order blocks every troupe pull request: the ruleset would require `check` before any run reports it.
Between 1 and 2, a troupe pull request that changes only `openspec/` skips its legs, and the 12 required contexts
never report, so it waits until the apply. Pull requests that change anything else run the legs and pass the old
ruleset. The window is as long as the infrastructure review.

The issue for it is opened in troupe-run/infrastructure and added to the roadmap board when this change's pull
request is opened. It's linked from this change's pull request.

## Risks / Trade-offs

- [`changes` adds a job before the legs] → About 20 to 30 seconds on a full run (checkout with history, uv, one
  `check-scope`). The legs take 3 to 8 minutes, and an `openspec/`-only pull request saves all of them.
- [A full-history checkout gets slower as the repository grows] → Only `changes` needs it. A shallow fetch of the
  base and head would do, but a wrong depth would make `git diff` fail, which runs the full check: safe, just slow.
  Revisit if `changes` takes more than a minute.
- [A scoped check misses a broken test elsewhere] → Only a test that reads none of the changed paths, so the change
  can't have broken it through what it reads. `main` runs the full check after every merge, and catches drift such
  as a dependency update.
- [A test reads a scoped path through a subprocess, which `guard_pytest` can't see] → The declaration's comment
  already says such tests are tagged by hand. Unchanged by this change; CI only uses what the commit guard already
  trusts.
- [`check` is a single job that must always run] → `if: always()`, no setup beyond checkout, and it fails on any
  result it doesn't recognise.
- [The window between the merge and the apply (D7)] → Only `openspec/`-only pull requests wait in it. Nothing merges
  untested.

## Migration Plan

1. Prove the workflow on the throwaway repository (D6), and delete it.
2. Merge this pull request.
3. Merge infrastructure's pull request changing troupe's required checks to `check`, and the owner approves the
   apply.
4. The next `openspec/`-only pull request in troupe shows it working in place: legs skipped, `check` green, mergeable.

Rollback, in the opposite order: first put troupe's 12 contexts back in infrastructure and apply. troupe's legs
still run under their names on every pull request that changes more than `openspec/`, so nothing blocks. Then revert
this change in troupe. Its pull request changes `ci.yml`, so it runs every leg, which the restored ruleset requires.
Reverting troupe first would block its own revert: the run would no longer report `check`, which the ruleset still
requires.
