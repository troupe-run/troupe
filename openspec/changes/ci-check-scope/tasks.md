# Tasks

## 1. ruff stops reading `openspec/` (design D4)

- [x] 1.1 Write the test first, in `scripts/tests/`: copy the repository's `pyproject.toml` into a temporary tree,
  write the same badly formatted Python block to `openspec/changes/x/design.md` and to `docs/x.md`, and run `ruff
  format --check .` there. Assert the run fails naming `docs/x.md` and doesn't name the `openspec/` file. Verify it
  fails on this branch before 1.2, on the `openspec/` half only.
- [x] 1.2 Add `extend-exclude = ["openspec"]` to `[tool.ruff]` in `pyproject.toml`. Verify the test from 1.1 passes,
  and `uv run ruff format --check -v .` lists no file under `openspec/`.
- [ ] 1.3 Run `uv run scripts/check.py` and commit (`build(ruff): stop formatting the code blocks in OpenSpec
  artifacts`).

## 2. The result judgement (design D3)

- [ ] 2.1 Write `scripts/check_result.py`, standard library only: three arguments (the legs' result, `changes`'
  result, the scope), exit 0 or 1, and one line saying why. Test each row of design D3's table in
  `scripts/tests/test_check_result.py`, including an unknown legs result and a wrong number of arguments (both fail,
  naming the input and what's valid). Verify the tests pass and `python3 scripts/check_result.py skipped success none`
  exits 0.
- [ ] 2.2 Add `scripts/check_result.py` to `scopes.scripts` in `scripts/check-paths.toml`. Verify `printf
  'scripts/check_result.py\nscripts/tests/test_check_result.py\n' | uv run --no-project scripts/guard.py check-scope`
  answers `scope=scripts`, and the reach check (`uv run scripts/check_paths_reach.py`) agrees with the declaration.
- [ ] 2.3 Run `uv run scripts/check.py` and commit (`feat(ci): judge the check legs' result in one script`).

## 3. The workflow (design D1, D2, D3, D5)

- [ ] 3.1 Add the `changes` job to `.github/workflows/ci.yml` as design D1 has it, pinned to the same action shas
  the workflow already uses. Verify locally that the run block works on this branch: `git diff --name-only
  --no-renames main...HEAD | uv run --no-project scripts/guard.py check-scope` prints `scope=` and `check-args=`
  lines.
- [ ] 3.2 Rename the matrix job's id to `check-legs`, keep its name, and add `needs: changes`, the `if` from design
  D2, and the check step with `shell: bash` and `CHECK_ARGS`. Verify `uv run scripts/check.py` still passes
  `python_versions`' matrix check (it reads the unchanged `python:` line).
- [ ] 3.3 Add the `check` result job from design D3. Add a header comment to `ci.yml` saying what each job does and
  why the legs aren't required themselves, as infrastructure's `ci.yml` does.
- [ ] 3.4 Update `README.md`'s CI sentence: a pull request runs what its paths need on all three platforms, `main`
  runs everything, and the required check is `check`. Verify the docs tests pass (`uv run scripts/check.py --scope
  docs`).
- [ ] 3.5 Run `uv run scripts/check.py` and commit (`feat(ci): run only the check a pull request's paths need`).

## 4. Proof before the merge (design D6)

- [ ] 4.1 With the owner's go-ahead, create `troupe-run/troupe-probe-ci-check-scope`, push this branch to it as
  `main`, and add a ruleset requiring `check`. Verify the push's run on its `main` runs `changes` skipped, 12 legs in
  full, and `check` green.
- [ ] 4.2 Open three pull requests there against its `main`: one changing only a file under `openspec/`, one only
  `docs/runs.md`, one a core file. Verify, and record the run links here: the first has 12 legs skipped (one check run
  under the unexpanded name), `check` green and the PR mergeable; the second runs `check.py --scope docs` on all 12
  legs; the third runs the full check on all 12.
- [ ] 4.3 Make `changes` fail on one more pull request there (point `BASE` at a sha that isn't in the clone, in that
  probe's copy of the workflow only). Verify `changes` fails, all 12 legs run the full check, and `check` reports their
  result.
- [ ] 4.4 Delete the probe repository with the owner's go-ahead. Verify `gh repo view
  troupe-run/troupe-probe-ci-check-scope` fails.

## 5. The required checks in infrastructure (design D7)

- [ ] 5.1 Open an issue in troupe-run/infrastructure for troupe's required checks to become `check` (`--project
  "troupe roadmap"`), saying it merges after this change's pull request, and why. Verify it's on the board with `gh
  issue view <n> -R troupe-run/infrastructure --json projectItems`, and link it from this change's pull request.

## Workflow follow-up

- Open this change's pull request with `Closes #101` and the probe evidence from 4.2 and 4.3. Its own run reports the
  12 legs (it changes `ci.yml`) and the new `check`.
- Archive the change on the branch before merging.
- After the merge: the infrastructure change from 5.1 goes through its own OpenSpec change, pull request and apply.
- After the apply: link the first `openspec/`-only troupe pull request that merged with its legs skipped on #101.
