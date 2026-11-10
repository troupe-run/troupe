# Tasks

## 1. The test: linked changelogs exist, and every part is shown

- [x] 1.1 Before changing the test, check whether #263 has merged (`gh pr view 263 -R troupe-run/troupe --json state`)
  and which of `plugins/runner-ollama/CHANGELOG.md`, `plugins/runner-openai/CHANGELOG.md` and
  `packages/troupe-plugin-sdk/CHANGELOG.md` exist on this branch after rebasing on `main`. Record the result in this
  task, since it decides 2.1 and 3.2. Verify by listing the files.
  Result (2026-11-11, rebased on `71c76ced`): #263 is open, and none of the three exist (`ls` finds the other 11
  changelogs only), so 2.1 names all three parts and 3.2 opens the follow-up.
- [x] 1.2 Add tests to `packages/troupe/tests/test_user_docs_changelog.py`, one for each delta scenario, using
  `CONFIG_SAMPLE` and a set of existing paths, and run them against the current `problems()` first. Expect "a link to
  a changelog not written yet" and "a part not released yet" to fail, and "a first release" to fail with the
  current signature only. The tests: a link to a changelog that doesn't exist fails, naming the page, the path and
  `` - `<component>` ``; the list item `` - `<component>` `` for a part with no changelog passes; that list item for a
  part whose changelog exists passes; a part neither linked nor listed fails, naming the part, its path and both
  fixes; a bare `` `<component>` `` in prose doesn't count as listed (D1). Each test's name says what its body checks.
- [x] 1.3 Change `problems()` to take the page, the config and a callable saying whether a path exists. Read each
  package's `component`, and fail naming the package if one has none. Find linked paths with `LINK` and listed parts by
  a list item that starts with `` `<component>` ``, and return D4's messages. Keep `written()` and the misnamed and
  custom-`changelog-path` tests passing unchanged in what they assert. Rename
  `test_the_page_links_exactly_the_changelogs_release_please_writes` to say what it now checks, and make it pass
  `(ROOT / path).is_file`. Update the module docstring to cite this change's design. Verify
  `uv run pytest packages/troupe/tests/test_user_docs_changelog.py` passes, and every test from 1.2 fails if the check
  it names is removed.
  Done: the misnamed test finds the same two problems, and its "doesn't link" message now names both fixes.
  Each new test failed with its check disabled (existence, listing, a list item rather than any code span, the
  component check).

## 2. The page

- [x] 2.1 In `docs/backstage/changelog.md`, replace each link to a changelog that doesn't exist on this branch (per
  1.1) with the list item `` - `<component>` ``. Keep the "starts with its first release" sentences, worded for the
  parts that are still unreleased. If none are, leave the page's links as they are and drop those sentences only if
  they no longer apply. Verify the real-page test from 1.3 passes, and `uv run pytest -m docs` passes.
  Done: the three parts are listed by name, and each "starts with its first release" sentence now says it's
  linked once it exists. `uv run pytest -m docs`: 190 passed.

## 3. Verification and follow-up

- [x] 3.1 Run the full check, `uv run scripts/check.py`, writing its output to a scratch file, and verify it passes.
  Done: all gates passed (tests in 404 s), after wrapping three lines ruff flagged on the first run.
- [x] 3.2 If 2.1 named any parts, open a Feature issue in troupe-run/troupe (on the roadmap board with
  `--project "troupe roadmap"`) to link their changelogs once #263 (or their first release) merges, citing #366 and
  this change. Verify with `gh issue view <n> -R troupe-run/troupe --json projectItems`. If 2.1 named none, record
  here that no follow-up is needed.
  Done: #368 (Feature, `documentation`), on the board in Todo.

## Workflow follow-up

- Open the draft pull request with `Closes #366`, act on Claude's review, mark it ready and archive on the branch.
- After the merge, comment on #366 with the PR and the archived change, and on troupe-run/website#112 to say `main`
  no longer links missing changelogs.
