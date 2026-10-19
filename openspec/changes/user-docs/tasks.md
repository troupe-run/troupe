# Tasks

## 1. The contributor docs move to `contributing/` (design D1; spec: quality-check)

- [x] 1.1 Before moving anything, run `uv run scripts/check.py --scope docs` on this branch and record which tests ran
  and passed. They are the non-goal "every existing doc test still holds", and must still run and pass after the move.
  - Done 2026-10-19 at `b8ece57`: every gate passed, `26 passed`. The 26 are `test_cli_docs` (5), `test_event_store_doc`
    (5), `test_exit_codes_doc` (1), `test_platform_docs` (2), `test_runners_doc` (5), `test_runs_doc` (7) and the
    scripted runner's `test_scripted_schemas::test_the_readmes_options_table_lists_exactly_the_options_schemas_properties`
    (1).
- [x] 1.2 `git mv` `docs/runs.md`, `runners.md`, `event-store.md`, `platform.md`, `releasing.md` and `flake-hunt.md` to
  `contributing/`. Leave `docs/cli/` for group 5. Verify `git log --follow contributing/runs.md` shows its history.
- [x] 1.3 Update every reference to the moved paths outside `openspec/changes/archive/`:
  - the root and package READMEs, `plugins/README.md`, `protocol/README.md` and `errors.schema.json`'s description;
  - the comments in `troupe.core.defaults`, `errors`, `notices` and `troupe.platform.processes`;
  - the scripts and `flake_hunt.Dockerfile`, `release.yml`'s comment, and the fixtures' `provenance.json`;
  - the doc tests' paths, and the links between the moved docs themselves.

  Verify `git grep -n -E "docs/(runs|runners|event-store|platform|releasing|flake-hunt)\.md" -- ':!openspec/changes/archive'`
  prints nothing, and every relative link in `contributing/` resolves (a one-off script, its output recorded here).
  - Done 2026-10-19: the grep prints only `openspec/specs/quality-check/spec.md`'s scenarios, which this change's delta
    updates (see its "Every test run keeps the declaration true"). `docs/cli/README.md`'s two links to runs point at
    `../../contributing/runs.md` until 5.2 folds the page. The link script over `contributing/*.md`, `docs/cli/*.md`
    and every README printed `broken: 0`.
- [x] 1.4 Add `contributing/**` to `[scopes.docs]` in `scripts/check-paths.toml`, updating its comment. Verify that
  `uv run scripts/guard.py check-scope` (or the command `scripts/tests/test_check_scope.py` uses) answers
  `--scope docs` for a path list holding only `contributing/runs.md`. Add that case to the declaration's tests. Then
  run the full check and record it passing.
  - Done 2026-10-19: `test_troupes_declaration_scopes_the_user_and_contributor_docs_to_docs` (in
    `scripts/tests/test_check_scope.py`) asks `guard.check_scope` about troupe's own declaration for
    `contributing/runs.md`, a `docs/` page and `contributing/` with `openspec/`: `("docs",)` each time. With the old
    declaration, `contributing/runs.md` answered `Scope(full=True, ...)`. The quality-check delta also carries
    "Every test run keeps the declaration true" with `contributing/runs.md` in its scenarios. Full check: all gates
    passed, `1898 passed, 7 skipped`.

## 2. The front matter check and the moved written pages (design D2; spec: user-docs)

- [ ] 2.1 Add `packages/troupe/tests/test_user_docs_front_matter.py` (tagged `docs`). It checks D2's closed key set
  and types, `planned` pages with a `purpose` and no body, and `written` pages with a body and an explicit
  `prerelease`. Duplicate YAML keys are refused, and every failure names the page and the key. Give each spec
  scenario a test against a page written to `tmp_path`: missing description, unknown key, planned page with text,
  written page without `prerelease`. Verify each fails before the check exists and passes after.
- [ ] 2.2 Copy the written pages from `troupe-run/website` `origin/main` as they are: `programme/what-is-troupe.md`,
  `programme/principles.md`, `backstage/licensing.md` and `prompt-book/glossary.md`.
  - Set `prerelease: true` explicitly on what-is-troupe and principles, and leave licensing and the glossary
    `false`.
  - Rewrite the glossary's `system` row as D5 gives it.
  - Record the website commit they were copied from in the commit message.

  Verify `diff` against `git -C ../website show origin/main:<path>` shows only those edits, and the front-matter test
  passes.
- [ ] 2.3 Add the 21 other placeholder pages as they are on the website (`status: planned`, their `purpose`), so the
  tree is complete before any is written. Change two things: first-theatre's purpose says "an existing project
  directory", and the guests page's title is "Guests". Verify the front-matter test passes, and that `find docs -name
  '*.md'` lists the 29 pages: 25 placeholders, plus the four written pages, which include the glossary.

## 3. The vocabulary and link checks (design D5, D7; spec: user-docs)

- [ ] 3.1 Add `packages/troupe/tests/test_user_docs_vocabulary.py` (tagged `docs`), porting the website's docs rules
  as D5 lists them. The recorded uses start with the moved pages' "project" lines, carrying the website's reasons.
  Give each spec scenario a test against `tmp_path` pages:
  - a new "project";
  - "repo" for a theatre;
  - a stale recorded use;
  - a term in code font;
  - a missing glossary term.

  Verify that the code-font test fails against the unfixed `system` row (the website's text), and passes on 2.2's.
- [ ] 3.2 Add `packages/troupe/tests/test_user_docs_links.py` (tagged `docs`), as D7. Test the slugger against
  github-slugger's documented cases, including punctuation, code spans and repeats. Give each spec scenario a test: a
  missing page, a missing anchor, and a relative link out of `docs/`. Verify all pass on the tree as it stands.
- [ ] 3.3 Run `uv run scripts/check.py --scope docs`. Verify that the new tests run with 1.1's, and that guard_pytest
  reports no untagged read.

## 4. Placeholder issues for the undecided subjects (design D6)

- [ ] 4.1 Open four placeholder Feature issues in troupe-run/troupe with `--project "troupe roadmap"`: flows (fork,
  join, swarm, loop), notes (improving between runs), escalation's research steps and decision brief, and guests and
  their manifest. Each holds only what D6's table cites as decided, the questions still to decide, and the pages that
  link it. Use `--body-file` with a file in the scratchpad. Verify each with `gh issue view <n> -R troupe-run/troupe
  --json projectItems`, and record the numbers in D6's table.

## 5. Generated reference (design D3; spec: user-docs)

- [ ] 5.1 Write `scripts/docs_reference.py` with the four regions in D3's table, and its `--check` mode. Rewriting
  must change only the text between a region's markers. Add a test for that: a page whose prose surrounds a stale
  region keeps its prose byte for byte, and the CRLF and LF forms of the page give the same result on every OS.
  Verify that `uv run scripts/docs_reference.py --check` exits non-zero naming each stale region, and that a second
  run changes nothing.
- [ ] 5.2 Build `docs/prompt-book/cli.md` from `docs/cli/README.md` (`git mv`) and `docs/cli/exit-codes.md`:
  - the prose sections are kept;
  - the `cli` and `exit-codes` regions replace the hand-written tables;
  - it gets the site's front matter, `prerelease: false`, with links fixed to GitHub URLs or user pages.

  Point `test_cli_docs` and `test_exit_codes_doc` at it. `test_exit_codes_doc` keeps checking the enum.
  - Review the help strings and the exit-code docstrings as reference prose (D3). Fix wording in the code, and
    verify that `test_cli.py`'s `--help` tests still pass.
  - Verify that `test_cli_docs`'s console examples pass, and that `docs/cli/` is gone.
- [ ] 5.3 Write `docs/prompt-book/events.md`: an introduction to events and lineage, linking the lineage concept
  page, then the `events` region. Verify the region lists `Run.Started`, `Run.Reported` and `Run.Ended` with every
  field in their schemas.
- [ ] 5.4 Write `docs/prompt-book/config-schema.md` as intent (D6), with the `config` region saying there's no config
  schema yet. Verify the no-schema scenario. Then in a test, add a minimal schema under a temporary
  `protocol/schemas/config/` and check that `--check` fails until it's regenerated.
- [ ] 5.5 Add `packages/troupe/tests/test_user_docs_reference.py` (tagged `docs`). It runs the `--check` mode and
  fails naming the page, the region and `uv run scripts/docs_reference.py`. Give each spec scenario a test: a new
  CLI option (a `Command` added in the test), an edit inside a region, and no config schema. Verify the full check
  passes.

## 6. The changelog page (design D4; spec: user-docs)

- [ ] 6.1 Write `docs/backstage/changelog.md` as D4 describes. Add
  `packages/troupe/tests/test_user_docs_changelog.py` (tagged `docs`), which compares the page's changelog paths
  with the packages in `release-please-config.json`, plus the misnamed-changelog scenario. Verify that it passes,
  and that it would still pass with the changes release PR #89 makes (rebase #89's files onto this branch in a
  throwaway worktree, run the test, and record the result).

## 7. The written pages (design D6; spec: user-docs)

Each page is written from D6's row and its cited sources, and nothing more. Each task's verification has two
parts:
- the front-matter, vocabulary and link tests pass;
- a review of each sentence about unbuilt behaviour against D6's sources, with the sentence and its source
  recorded under the task.

A built claim with an example is checked by a docs test, as `test_cli_docs` checks console examples.

- [ ] 7.1 Opening night: `install`, `first-theatre` and `first-performance`. first-performance's console examples
  run as written under a test (scripted runner, policy set, in a temporary theatre). Verify that test passes on
  every OS in CI.
- [ ] 7.2 The company, built parts first: `theatres`, `performances-and-runs`, `lineage` and `roles-and-actors`.
  They say plainly that `perform` runs one actor today, and that `system` is decided but not yet recorded. Verify
  the lineage fields they list match `lineage.schema.json`, by a test or by linking the generated events page
  instead of repeating them.
- [ ] 7.3 The company, intent: `the-house` and `gates-and-decisions`. Undecided: `escalation`, `flows`, `guests` and
  `notes`, each linking its 4.1 issue. Verify each `prerelease: true` and the review record.
- [ ] 7.4 Stagecraft: `bring-your-own-agent` (the runner contract and conformance suite, linking
  `contributing/runners.md` by its GitHub URL), `read-the-lineage`, `configure-roles`, `hand-edit-config`,
  `route-decisions`, `build-a-flow` and `write-a-guest`. Also the prompt book's `guest-manifest`. Verify each as
  above.
- [ ] 7.5 Verify no page under `docs/` is still `status: planned`. A test asserts it, so a page added later in the
  planned state must either be written or have that assertion relaxed in its own change.

## 8. Integration

- [ ] 8.1 Run `uv run scripts/check.py` and `uv run scripts/check.py --scope docs`. Verify that both pass, and that
  the scoped run runs exactly the `docs`-tagged tests: 1.1's, plus the new ones.
- [ ] 8.2 Verify that a commit staging only a page under `docs/` runs `--scope docs` through the commit guard, and
  that one staging only `scripts/docs_reference.py` runs the full check.

## Workflow follow-up

- Open the pull request with `Closes #123`. The description should:
  - list the moved contributor docs;
  - name the conflict over the rebuild notice (design D9) for the owner to confirm;
  - list what's left to website#23: the loader, removing the pages from the website, the brand guide's §6 link and
    `system` row, and the vocabulary test's `GLOSSARY` constant.
- Comment on website#23 with this change's page tree, the front-matter keys (D2) and the changelog page's approach
  (D4).
- Archive the change on the branch before merging. After the merge, comment on #123 with the PR and the archived
  change, and check that the issue is closed and its card says Done.
