# Tasks

## 1. ruff stops reading `openspec/` (design D4)

- [x] 1.1 Write the test first, in `scripts/tests/`: copy the repository's `pyproject.toml` into a temporary tree,
  write the same badly formatted Python block to `openspec/changes/x/design.md` and to `docs/x.md`, and run `ruff
  format --check .` there. Assert the run fails naming `docs/x.md` and doesn't name the `openspec/` file. Verify it
  fails on this branch before 1.2, on the `openspec/` half only.
- [x] 1.2 Add `extend-exclude = ["openspec"]` to `[tool.ruff]` in `pyproject.toml`. Verify the test from 1.1 passes,
  and `uv run ruff format --check -v .` lists no file under `openspec/`.
- [x] 1.3 Run `uv run scripts/check.py` and commit (`build(ruff): stop formatting the code blocks in OpenSpec
  artifacts`).

## 2. The result judgement (design D3)

- [x] 2.1 Write `scripts/check_result.py`, standard library only: three arguments (the legs' result, `changes`'
  result, the scope), exit 0 or 1, and one line saying why. Test each row of design D3's table in
  `scripts/tests/test_check_result.py`, including an unknown legs result and a wrong number of arguments (both fail,
  naming the input and what's valid). Verify the tests pass and `python3 scripts/check_result.py skipped success none`
  exits 0.
- [x] 2.2 Add `scripts/check_result.py` to `scopes.scripts` in `scripts/check-paths.toml`. Verify `printf
  'scripts/check_result.py\nscripts/tests/test_check_result.py\n' | uv run --no-project scripts/guard.py check-scope`
  answers `scope=scripts`, and the reach check (`uv run scripts/check_paths_reach.py`) agrees with the declaration.
- [x] 2.3 Run `uv run scripts/check.py` and commit (`feat(ci): judge the check legs' result in one script`).

- [x] 2.4 Write `scripts/check_range.py`, standard library only: five arguments (the action, `before`, the base,
  the head, `before`'s `check` conclusion), printing the revisions to diff as design D1's table has them. Test each
  row in `scripts/tests/test_check_range.py`, and each refusal: a sha that isn't 40 lowercase hex characters (in each
  sha position, an empty `before` on `synchronize` included), an unknown action, a wrong number of arguments. Each
  refusal exits 1 naming the input and what's valid, and prints nothing on stdout. Verify the tests pass.
- [x] 2.5 Add `scripts/check_range.py` to `scopes.scripts` in `scripts/check-paths.toml`. Verify `check-scope`
  answers `scope=scripts` for it and its test, and the reach check agrees with the declaration.
- [ ] 2.6 Run `uv run scripts/check.py` and commit (`feat(ci): decide which revisions a push's check diffs`).

## 3. The workflow (design D1, D2, D3, D5)

- [x] 3.1 Add the `changes` job to `.github/workflows/ci.yml` as design D1 has it, pinned to the same action shas
  the workflow already uses. Verify locally that the run block works on this branch: `git diff --name-only
  --no-renames main...HEAD | uv run --no-project scripts/guard.py check-scope` prints `scope=` and `check-args=`
  lines.
- [x] 3.2 Rename the matrix job's id to `check-legs`, keep its name, and add `needs: changes`, the `if` from design
  D2, and the check step with `shell: bash` and `CHECK_ARGS`. Verify `uv run scripts/check.py` still passes
  `python_versions`' matrix check (it reads the unchanged `python:` line).
- [x] 3.3 Add the `check` result job from design D3. Add a header comment to `ci.yml` saying what each job does and
  why the legs aren't required themselves, as infrastructure's `ci.yml` does.
- [x] 3.4 Update `README.md`'s CI sentence: a pull request runs what its paths need on all three platforms, `main`
  runs everything, and the required check is `check`. Verify the docs tests pass (`uv run scripts/check.py --scope
  docs`).
- [x] 3.5 Run `uv run scripts/check.py` and commit (`feat(ci): run only the check a pull request's paths need`).
- [ ] 3.6 Rework the `changes` job as revised design D1 has it: `permissions: checks: read`, the event's action,
  `before`, base, head and repository in `env`, the `git cat-file -e` test, the check-runs lookup filtered by name
  and app id 15368, `check_range.py`, and `git diff` on its revisions. Verify it with actionlint, and run the step's
  script locally on this branch twice: with `synchronize`, `before` = `HEAD~1`, and the conclusion `success`
  (expect the paths of the last commit only), and with the conclusion `failure` (expect the whole branch's paths).
  Run the real lookup with `gh api` for this branch's pushed head and record what it returns.
- [ ] 3.7 Update `ci.yml`'s header comment and the README's CI sentence: a push is judged against the last push that
  passed, or the whole pull request when there's none. Verify `uv run scripts/check.py --scope docs` passes.
- [ ] 3.8 Run `uv run scripts/check.py` and commit (`feat(ci): judge each push against the last one that passed`).

## 4. Proof before the merge (design D6)

- [ ] 4.1 With the owner's go-ahead, create `troupe-run/troupe-probe-ci-check-scope`, push this branch to it as
  `main`, and add a ruleset requiring `check`. Verify the push's run on its `main` runs `changes` skipped, 12 legs in
  full, and `check` green.
- [ ] 4.2 On pull request A there, push in turn: a core change; then only an `openspec/` file; then only
  `docs/runs.md`; then a force push that rewrites the history with the same code and one more `openspec/` file.
  Verify each push's run against design D6's table, and record its link here: the full check on 12 legs; legs skipped
  (one check run under the unexpanded name) with `check` green and the pull request mergeable; `--scope docs` on 12
  legs; legs skipped again.
- [ ] 4.3 On pull request B, push a core change that fails a test, then only an `openspec/` file. Verify the second
  run diffs the whole pull request (its `changes` log says so) and runs the full check, and that `check` fails both
  times. Record the links.
- [ ] 4.3b On pull request C, make `changes` fail (a malformed sha, in that probe's copy of the workflow only).
  Verify `changes` fails, all 12 legs run the full check, and `check` reports their result. Record the link.
- [ ] 4.4 Delete the probe repository with the owner's go-ahead. Verify `gh repo view
  troupe-run/troupe-probe-ci-check-scope` fails.

## 5. The required checks in infrastructure (design D7)

- [ ] 5.1 Open an issue in troupe-run/infrastructure for troupe's required checks to become `check` (`--project
  "troupe roadmap"`), saying it merges straight after this change's pull request, and why: until it's applied, every push that skips the
  legs blocks its pull request (design D7). Open its pull request ready to merge before this one merges. Verify it's on the board with `gh
  issue view <n> -R troupe-run/infrastructure --json projectItems`, and link it from this change's pull request.

## Workflow follow-up

- Open this change's pull request with `Closes #101` and the probe evidence from 4.2, 4.3 and 4.3b. Its own run reports the
  12 legs (it changes `ci.yml`) and the new `check`.
- Archive the change on the branch before merging.
- Before this merges, the infrastructure change from 5.1 has its own OpenSpec change and pull request, ready to
  merge. Straight after this merges, it merges and the owner approves the apply.
- After the apply: link on #101 the first troupe archive push whose legs were skipped.
