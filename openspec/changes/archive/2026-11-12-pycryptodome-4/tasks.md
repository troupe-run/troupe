# Tasks

## 1. Update pycryptodome to 4.2.0

- [x] 1.1 In the root `pyproject.toml`'s `dev` group, change `"pycryptodome>=3.23"` to `"pycryptodome>=4.2.0"`, keeping the comment above it (design D2). Run `uv lock --upgrade-package pycryptodome==4.2.0` (a bare upgrade picks 4.4.0, design D2), then `uv sync --locked`. Verify `uv run python -c "import Crypto; print(Crypto.__version__)"` prints `4.2.0`, and that `git diff -- pyproject.toml uv.lock` matches `gh pr diff 343 -R troupe-run/troupe`: the same specifier line, the same pycryptodome entry (4.2.0, its sdist and its 17 wheels), and the same dev-group specifier, with nothing else changed.
- [x] 1.2 Run eventsourcing's suite against 4.2.0: `uv run pytest packages/troupe-store-text/tests/test_library_suite.py -k cipher -v`. Verify the cipher cases (`test_mapper_with_cipher`, `test_mapper_with_cipher_and_compressor`, `test_mapper_with_wrong_cipher_key`) are collected and pass, and are not skipped. Then run the whole file and verify it passes (design D1).
- [x] 1.3 Commit as `chore(deps-dev): update pycryptodome to 4.2.0`, signed and signed off (`git commit -S -s`), with `uv run scripts/check.py` passing. Write the check's full output to a scratch file and verify it ends in a pass, with mypy and the troupe-store-text suite in it.

## 2. Pull request

- [x] 2.1 Open a draft pull request that closes #250 (`gh pr create --draft --body-file <literal path>`), linking Dependabot's #343 and this change's design D1. Act on Claude's review of the last push, and mark it ready once the review is clean. Verify every CI leg passes, on Linux, macOS and Windows, Python 3.12 to 3.15.

## Workflow follow-up

- Run `/opsx:archive` on the branch before the merge.
- Ask the owner to merge, through the orchestrating session "troupe" ("#250 needs: …").
- After the merge: check #250 is closed and its card says Done, and comment on it with the pull request and the
  archived change. Then check #343: if Dependabot hasn't closed it as up to date, close it with a comment linking
  the merged pull request (design D3). Don't close #343 before the merge: that closes #250 as not planned.
