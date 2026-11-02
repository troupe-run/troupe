# Tasks

## 1. The check that every workspace member is ignored

- [x] 1.1 Write `scripts/tests/workspace/test_dependabot_members.py` first, copying the real root and member
  `pyproject.toml` files and `.github/dependabot.yml` into `tmp_path` (the `test_bundle.py` pattern). Give each spec
  scenario its own test: a member named outside the ignores, an ignore limited by `versions`, one limited by
  `update-types`, case/`_`/`.` differences that still match, `*` matching any run (including none) while `?` and
  `[` stay literal, and a missing file, unparseable YAML, no `uv` entry, or a `uv` entry for another directory. Plus
  one test on the real repository. Verify: the real-repository test fails on today's `main` (no ignores yet),
  naming `troupe` and every other member, and the copies' tests fail because the module doesn't exist.
- [x] 1.2 Add `scripts/dependabot_members.py` with `problems(root: Path) -> list[str]` (design D3 to D5): members from
  `release_config.members`, names normalised with `release_config.normalise`, `*`-only patterns built with
  `re.escape`, only ignores with neither `versions` nor `update-types` counting. Each message names the member,
  `.github/dependabot.yml`, and the fix in troupe-run/infrastructure's `tofu/dependabot.json`. Verify:
  `uv run pytest scripts/tests/workspace/test_dependabot_members.py` passes for every copy-based test, and the
  real-repository test still fails, listing exactly the members, until group 3. It's marked strict `xfail`
  (citing infrastructure#259) so commits pass meanwhile; strict means it fails once the ignores arrive.
- [x] 1.3 Verify the module carries no `packages/<name>` literal, and that `uv run scripts/check_paths_reach.py`
  reports no change to any scope's `tests` list (`scripts/tests/test_check_paths_reach.py` passes).

## 2. Docs

- [x] 2.1 In `contributing/releasing.md`, "Adding a package": a new member must be matched by Dependabot's `uv`
  ignores (`troupe` and `troupe-*`). If its name doesn't match, add it in troupe-run/infrastructure's
  `tofu/dependabot.json`, and `scripts/check.py` fails until it's delivered. Say why: a member moves only through its
  own release, and a same-named package on PyPI breaks Dependabot's run (#254). Verify: the `docs`-tagged tests pass
  (`uv run pytest -m docs`).

## 3. The ignore, delivered from infrastructure (troupe-run/infrastructure#259)

- [x] 3.1 infrastructure#259 merged and applied: its policy declares `troupe` and `troupe-*` as ignores for troupe's
  `uv` entry. Verify: `git fetch && git show origin/main:.github/dependabot.yml` has an `ignore` list in the `uv`
  entry naming both, each with no `versions` or `update-types`.
- [x] 3.2 Rebase this branch onto `main` with the delivered file, and remove the real-repository test's `xfail`.
  Verify: that test now passes, and `uv run scripts/check.py` passes.

## 4. Integration

- [x] 4.1 Differential check: with the delivered file, remove `troupe-*` from a copy and confirm the check names every
  `troupe-*` member and not `troupe`. Then remove `troupe` and confirm it names only `troupe` (covered by 1.1's
  tests; re-run them on the rebased branch). Verify: `uv run pytest scripts/tests/workspace/test_dependabot_members.py`.
- [x] 4.2 Ask the owner to run Dependabot's "Check for updates" for `uv` in troupe (Insights → Dependency graph →
  Dependabot), since the ignore takes effect once it's on `main`. Read the run's log
  (`gh run view <id> --log | grep -a "troupe"`). Verify: no "Updating troupe" or other member, no
  `dependency_file_not_resolvable`, and the run concludes `success`. If it's not run before archive, record that in
  the PR and check Monday's scheduled run instead.

## Workflow follow-up

- Open a draft PR that `Closes #254`, act on Claude's review of the last push, then mark it ready.
- Archive the change on the branch before the owner merges.
- After the merge, comment on #254 with the PR and the archived change, close infrastructure#259 if its own PR
  didn't, and check both cards say Done.
