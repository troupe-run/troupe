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

- [x] 2.1 Add `packages/troupe/tests/test_user_docs_front_matter.py` (tagged `docs`). It checks D2's closed key set
  and types, `planned` pages with a `purpose` and no body, and `written` pages with a body and an explicit
  `prerelease`. Duplicate YAML keys are refused, and every failure names the page and the key. Give each spec
  scenario a test against a page written to `tmp_path`: missing description, unknown key, planned page with text,
  written page without `prerelease`. Verify each fails before the check exists and passes after.
  - Done 2026-10-19: the parser is a strict subset of YAML (design D2, updated), with no new dependency. Run against
    the tree before 2.2, the real-tree test failed on `cli/README.md` and `cli/exit-codes.md` ("doesn't start with
    front matter"), and each scenario test asserts its exact message. Both CLI pages got front matter ahead of 5.2,
    and their H1s became their titles. `48 passed`.
- [x] 2.2 Copy the written pages from `troupe-run/website` `origin/main` as they are: `programme/what-is-troupe.md`,
  `programme/principles.md`, `backstage/licensing.md` and `prompt-book/glossary.md`.
  - Set `prerelease: true` explicitly on what-is-troupe and principles, and leave licensing and the glossary
    `false`.
  - Rewrite the glossary's `system` row as D5 gives it.
  - Record the website commit they were copied from in the commit message.

  Verify `diff` against `git -C ../website show origin/main:<path>` shows only those edits, and the front-matter test
  passes.
  - Done 2026-10-19 from website `32269c7`: the diffs show only `prerelease: true` on the two programme pages and the
    `system` row.
- [x] 2.3 Add the 21 other placeholder pages as they are on the website (`status: planned`, their `purpose`), so the
  tree is complete before any is written. Change two things: first-theatre's purpose says "an existing project
  directory", and the guests page's title is "Guests". Verify the front-matter test passes, and that `find docs -name
  '*.md'` lists the 29 pages: 25 placeholders, plus the four written pages, which include the glossary.
  - Done 2026-10-19: 29 pages from the website, plus `docs/cli/`'s two until 5.2 (31). first-theatre's `description`
    also said "a repo", so it says "a project directory" too. The diffs show only these edits.

## 3. The vocabulary and link checks (design D5, D7; spec: user-docs)

- [x] 3.1 Add `packages/troupe/tests/test_user_docs_vocabulary.py` (tagged `docs`), porting the website's docs rules
  as D5 lists them. The recorded uses start with the moved pages' "project" lines, carrying the website's reasons.
  Give each spec scenario a test against `tmp_path` pages:
  - a new "project";
  - "repo" for a theatre;
  - a stale recorded use;
  - a term in code font;
  - a missing glossary term.

  Verify that the code-font test fails against the unfixed `system` row (the website's text), and passes on 2.2's.
  - Done 2026-10-19: `13 passed`. Against website `32269c7`'s glossary, `glossary_problems` gave "the term
    '`system`' is in code font..." and "the glossary has no row for system". Against 2.2's glossary it gives nothing.
- [x] 3.2 Add `packages/troupe/tests/test_user_docs_links.py` (tagged `docs`), as D7. Test the slugger against
  github-slugger's documented cases, including punctuation, code spans and repeats. Give each spec scenario a test: a
  missing page, a missing anchor, and a relative link out of `docs/`. Verify all pass on the tree as it stands.
  - Done 2026-10-19: `26 passed`. On its first run against the tree, the check found two real problems:
    - `docs/cli/README.md` linked `../../contributing/runs.md` and `../../protocol/...` out of `docs/`. They're now
      GitHub URLs.
    - `programme/what-is-troupe.md` linked the site path `/docs/programme/status-and-roadmap/`. That page stays with
      the website and moves out of `/docs` (website#23), so a site path is now refused with a fix, and the link is
      `https://troupe.run/docs/programme/status-and-roadmap/`. website#23 must keep that URL or redirect it: this
      goes in the PR's list for website#23.

    The slugger first dropped the underscores of `troupe_vcs_git` inside a code span, and its tests caught that.
- [x] 3.3 Run `uv run scripts/check.py --scope docs`. Verify that the new tests run with 1.1's, and that guard_pytest
  reports no untagged read.
  - Done 2026-10-19: all gates passed, `113 passed` (74 + 13 + 26), with no guard_pytest failure.

## 4. Placeholder issues for the undecided subjects (design D6)

- [x] 4.1 Open four placeholder Feature issues in troupe-run/troupe with `--project "troupe roadmap"`: flows (fork,
  join, swarm, loop), notes (improving between runs), escalation's research steps and decision brief, and guests and
  their manifest. Each holds only what D6's table cites as decided, the questions still to decide, and the pages that
  link it. Use `--body-file` with a file in the scratchpad. Verify each with `gh issue view <n> -R troupe-run/troupe
  --json projectItems`, and record the numbers in D6's table.
  - Done 2026-10-19: #124 flows, #125 notes, #126 escalation, #127 guests, each a Feature with its `cap:` label, and
    each `troupe roadmap: Todo` by `gh issue view --json projectItems`. Recorded in D6.

## 5. Generated reference (design D3; spec: user-docs)

- [x] 5.1 Write `scripts/docs_reference.py` with the four regions in D3's table, and its `--check` mode. Rewriting
  must change only the text between a region's markers. Add a test for that: a page whose prose surrounds a stale
  region keeps its prose byte for byte, and the CRLF and LF forms of the page give the same result on every OS.
  Verify that `uv run scripts/docs_reference.py --check` exits non-zero naming each stale region, and that a second
  run changes nothing.
  - Done 2026-10-19: `scripts/docs_reference.py`. Tests cover four things:
    - prose kept byte for byte around a stale region, LF and CRLF;
    - LF and CRLF giving the same text;
    - a second run changing nothing;
    - refusals: a missing region, a region on the wrong page, a field with no description, an exit code with no
      docstring.

    `--check` exits 1 naming each stale region and the command, and 2 for a refusal. The usage line and the tables are
    built from the parsers' actions, never argparse's formatter, whose output changes between Python versions.
- [x] 5.2 Build `docs/prompt-book/cli.md` from `docs/cli/README.md` (`git mv`) and `docs/cli/exit-codes.md`:
  - the prose sections are kept;
  - the `cli` and `exit-codes` regions replace the hand-written tables;
  - it gets the site's front matter, `prerelease: false`, with links fixed to GitHub URLs or user pages.

  Point `test_cli_docs` and `test_exit_codes_doc` at it. `test_exit_codes_doc` keeps checking the enum.
  - Review the help strings and the exit-code docstrings as reference prose (D3). Fix wording in the code, and
    verify that `test_cli.py`'s `--help` tests still pass.
  - Verify that `test_cli_docs`'s console examples pass, and that `docs/cli/` is gone.
  - Done 2026-10-19: `docs/cli/README.md` moved to `docs/prompt-book/cli.md` (`git mv`) and `exit-codes.md` is
    gone.
    - The commands' and global flags' tables became the `cli` region, with what they said beyond the help strings kept
      as prose.
    - `--expect`'s help now says "relative to where you are and inside the theatre".
    - CANCELLED's docstring now reads as the page did ("You cancelled...").
    - The runs links point at `contributing/runs.md` by GitHub URL until 7.2 writes the performances-and-runs page.

    `test_cli_docs` (5) and `test_exit_codes_doc` pass against the new page. No test pins the help strings, and the
    full check at commit runs `test_cli.py`.
- [x] 5.3 Write `docs/prompt-book/events.md`: an introduction to events and lineage, linking the lineage concept
  page, then the `events` region. Verify the region lists `Run.Started`, `Run.Reported` and `Run.Ended` with every
  field in their schemas.
  - Done 2026-10-19. Generating the page found two fields with no description, `Run.Ended.outcome` and
    `Run.Reported.seq`. Their schemas now describe them (`seq` from the runner contract: it starts at 0), and the
    generator refuses a field with no description from now on. `test_the_events_page_lists_every_event_schema_with_every_field`
    checks each event's title and every field.
- [x] 5.4 Write `docs/prompt-book/config-schema.md` as intent (D6), with the `config` region saying there's no config
  schema yet. Verify the no-schema scenario. Then in a test, add a minimal schema under a temporary
  `protocol/schemas/config/` and check that `--check` fails until it's regenerated.
  - Done 2026-10-19: the page states what #6, #7 and #60 decide and that the rest is #60's design, and is
    `prerelease: true`. `test_with_no_config_schema_the_region_says_so_and_a_new_schema_makes_it_stale` adds
    `config/actor.schema.json` to a copy: `--check` fails naming the region, and regenerating lists the `runner` field.
- [x] 5.5 Add `packages/troupe/tests/test_user_docs_reference.py` (tagged `docs`). It runs the `--check` mode and
  fails naming the page, the region and `uv run scripts/docs_reference.py`. Give each spec scenario a test: a new
  CLI option (a `Command` added in the test), an edit inside a region, and no config schema. Verify the full check
  passes.
  - Done 2026-10-19: `16 passed`. `uv run scripts/check.py --scope docs`: all gates passed, `127 passed`. The full
    check runs at this group's commit.

## 6. The changelog page (design D4; spec: user-docs)

- [x] 6.1 Write `docs/backstage/changelog.md` as D4 describes. Add
  `packages/troupe/tests/test_user_docs_changelog.py` (tagged `docs`), which compares the page's changelog paths
  with the packages in `release-please-config.json`, plus the misnamed-changelog scenario. Verify that it passes,
  and that it would still pass with the changes release PR #89 makes (rebase #89's files onto this branch in a
  throwaway worktree, run the test, and record the result).
  - Done 2026-10-19. The page links the nine changelogs, grouped as the linked `troupe` release and the plugins
    (`contributing/releasing.md`), and the test passes (4 tests).
  - The check against #89 was lighter than the task says. #89 (fetched as `pull/89/head`) changes neither `docs/` nor
    `release-please-config.json`, the only two files the test reads. So instead of rebasing, I ran `problems()`
    against #89's config: `[]`. All nine `CHANGELOG.md` files #89 writes are among those the page links.

## 7. The written pages (design D6; spec: user-docs)

Each page is written from D6's row and its cited sources, and nothing more. Each task's verification has two
parts:
- the front-matter, vocabulary and link tests pass;
- a review of each sentence about unbuilt behaviour against D6's sources, with the sentence and its source
  recorded under the task.

A built claim with an example is checked by a docs test, as `test_cli_docs` checks console examples.

- [x] 7.1 Opening night: `install`, `first-theatre` and `first-performance`. first-performance's console examples
  run as written under a test (scripted runner, policy set, in a temporary theatre). Verify that test passes on
  every OS in CI.
  - Done 2026-10-19 (CI on every OS runs with the pull request). `test_user_docs_pages.py`:
    - `test_the_first_performance_runs_as_written_and_writes_its_file` takes the page's `hello.json` block and `sh`
      lines in a fresh git theatre with the policy unset, runs `perform`, `status` and `logs` as written, and checks
      the run succeeds and writes `out/hello.txt`;
    - `..._is_refused_until_the_policy_is_set` shows the page's policy step is needed;
    - `test_the_install_page_gives_the_python_versions_troupe_declares` checks the install page against
      `requires-python`.

    Review of unbuilt claims:
    - install: no install method, #38 q4 (open); releases on GitHub with changelogs, releases spec (built); CLI and
      house as one unit, #73; `~/.troupe/` and `TROUPE_HOME`, #2.
    - first-theatre: config by convention, #6; `$schema`, #7; `troupe config set`, #60. The draft said git was
      optional, but `perform` always uses git today (`defaults.VCS`), so that part was rewritten: plain files are
      built but can't be chosen until #60, and #121 is open. The draft also said "a setup command arrives with #60",
      which nothing decides. The page now says it's an open question on #60, raised there:
      https://github.com/troupe-run/troupe/issues/60#issuecomment-6267832585.
    - first-performance: the Claude Code runner, #55; the interim flags, #60; a whole-process performance needs flows,
      roles and gates (#124, #61, #62). "The run fails if it wasn't [changed]" is the actor-runners spec ("Success
      needs ... a passing effect check").
- [x] 7.2 The company, built parts first: `theatres`, `performances-and-runs`, `lineage` and `roles-and-actors`.
  They say plainly that `perform` runs one actor today, and that `system` is decided but not yet recorded. Verify
  the lineage fields they list match `lineage.schema.json`, by a test or by linking the generated events page
  instead of repeating them.
  - Done 2026-10-19. Tests in `test_user_docs_pages.py`:
    - the runs page's states table equals `State`, its listed events equal the run aggregate's `TOPICS`, and its
      policy row and variable equal `troupe.core.policy` and `defaults`;
    - the lineage page names exactly the lineage schema's properties.

    Review of unbuilt claims:
    - theatres: config under `.troupe/`, #60; typed references, #6; `$schema` and per-kind schemas, #7; config only
      in the theatre, #2; guests' own files, #6 and #7; policy files open, #8.
    - performances-and-runs: rehearsal, #15; worktree per run, #51 (planned); Docker stage, #65 (planned); the house
      supervising runs, #73.
    - lineage: roles in lineage, #15 and #61; #44 open; approvals with gates, #62; `system` decided but not recorded
      (`lineage.schema.json` allows `human` and `agent`, plus `unknown`).
    - roles-and-actors: work to roles, holders and roles in lineage, and `system`, #15; config of holders, #61;
      actor files, #6 and #60; #44 open.
- [x] 7.3 The company, intent: `the-house` and `gates-and-decisions`. Undecided: `escalation`, `flows`, `guests` and
  `notes`, each linking its 4.1 issue. Verify each `prerelease: true` and the review record.
  - Done 2026-10-19. All six are `prerelease: true`, which the front-matter test reads.
    - the-house: every point is from #73's decision (only orchestrator, exceptions, per user, B1 auto-start with a
      notice, start/stop "or similar" as provisional names, one unit, events stay the truth); #2 (own settings and
      store, `TROUPE_HOME`); #118 (auto-start off); #14 (gateway: localhost, token, refuses failing requests, pushed
      updates, no policy in a request). The open details are #63's own list.
    - gates-and-decisions: #15 (to roles, cues, notifications and inbox), #62 (a flow stops at a gate, the answer
      with lineage), #73 (works with nobody at a terminal), #12 (open). Cut: "and carries on once it's given", which
      #62 doesn't say.
    - escalation: research then brief (principles, glossary); to a role and raising a cue (#15). The rest is on #126.
    - flows: the principle, and #62's gate. The rest is on #124.
    - guests: own files and schemas (#6, #7); acquired ones over JSON-RPC (#37). The draft stated #38's
      direction (named and pinned in config) as decided; it's now a leaning, under "Not decided yet". The rest is on
      #127.
    - notes: the term (#15) and the glossary line. The rest is on #125.
- [x] 7.4 Stagecraft: `bring-your-own-agent` (the runner contract and conformance suite, linking
  `contributing/runners.md` by its GitHub URL), `read-the-lineage`, `configure-roles`, `hand-edit-config`,
  `route-decisions`, `build-a-flow` and `write-a-guest`. Also the prompt book's `guest-manifest`. Verify each as
  above.
  - Done 2026-10-19.
    - bring-your-own-agent: the contract and the conformance suite are built (runner-protocol spec,
      `contributing/runners.md`). That `perform` can't run your own runner yet is `troupe.core.interim.RUNNERS`. #55
      and #56 are planned; JSON-RPC for all plugins and policy over transports, #37; SDK, #58; #38 and #67 open.
    - read-the-lineage: a first draft said `logs --json` shows each event's change and cause. The client schemas say
      otherwise: `loggedEvent` holds `seq`, `at` and the event, and `summary` holds `startedBy` and `stage`. The page
      now says the full lineage is only in `.troupe/events/`, and that no command shows it yet. Cut: a bullet about
      an undecided lineage command, which had no issue to link.
    - configure-roles: #15, #61, #9 (an agent's identity from its actor), #6 and #60; #44 open.
    - hand-edit-config: #5 (net change at command boundaries, no watching), #119 (mid-save guard, surgical write-back,
      unknown author), #60 (a hand-edited file refused until #119), the project constraint that formatting is kept
      whichever surface writes, #45 (keep or drop, asked: #1 named it).
    - route-decisions: #15, #62, #73; #61, #44 and #12 open. Notification channels only as #12's leaning.
    - guest-manifest: #6 and #7 only; the format is on #127. Cut: a promise that the page would be generated, which
      nothing decides.
- [x] 7.5 Verify no page under `docs/` is still `status: planned`. A test asserts it, so a page added later in the
  planned state must either be written or have that assertion relaxed in its own change.
  - Done 2026-10-19: `test_no_page_is_still_planned` passes. The vocabulary list records five more uses, each with
    its reason, and every relative link resolves (`test_user_docs_links`).

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
