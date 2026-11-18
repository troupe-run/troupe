# Tasks

## 1. Regenerate config's models under 0.92

- [x] 1.1 With Dependabot's commit as the branch's base, run `uv sync --locked` and verify `uv run python -c "import importlib.metadata as m; print(m.version('datamodel-code-generator'))"` prints `0.92.0`. Verify `git show HEAD --stat` changes only `pyproject.toml` and `uv.lock`, matching `gh pr diff 445 -R troupe-run/troupe`.
- [x] 1.2 Run `uv run scripts/generate_models.py`, then verify `uv run scripts/generate_models.py --check` exits 0 and `git diff --stat` touches only `models.py`. Compare `ast.dump(ast.parse(...))` of `git show HEAD:packages/troupe/src/troupe/core/config/models.py` and the regenerated file, and verify they're identical (design D1).
- [x] 1.3 Verify `uv run pytest packages/troupe/tests/test_config_schemas.py` passes, including `test_the_models_are_what_the_schemas_generate`.
- [x] 1.4 Commit `models.py` as `style(config): regenerate config's models under datamodel-code-generator 0.92`, signed and signed off (`git commit -S -s`), with `uv run scripts/check.py` passing (design D2). Write the check's full output to a scratch file and verify it ends in a pass.

## 2. Pull request

- [x] 2.1 Push the branch and open a draft pull request that closes #447 and #432 (`gh pr create --draft --body-file <literal path>`), linking Dependabot's #445 and design D1. Act on Claude's review of the last push, and mark it ready once the review is clean. Verify every CI leg passes, on Linux, macOS and Windows.

## Workflow follow-up

- Run `/openspec-archive-change` on the branch before the merge.
- Ask the owner to merge, through the orchestrating session "troupe" ("#447 needs: …").
- After the merge: check #447 and #432 are closed and their cards say Done, and comment on #447 with the pull
  request and the archived change. Then check #445: if Dependabot hasn't closed it as up to date, close it with a
  comment linking the merged pull request (design D3). Don't close #445 before the merge: that closes #432 as not
  planned.
