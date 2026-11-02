# Tasks

## 1. The VCS port says whether a directory is in a repository

- [x] 1.1 Add `vcs.not-a-repository` to `troupe.core.errors` (exit 1) and its details schema (`directory`,
  `adapter`) to `protocol/schemas/error.schema.json`. Verify with the error-schema test, which checks every
  registered code has a details schema.
- [x] 1.2 Add `check_repository()` to the `Vcs` protocol, and implement it in `troupe-vcs-files` (always passes) and
  in any test fakes of the port. Verify with mypy --strict and the files adapter's test for the new scenario.
- [x] 1.3 Implement it in `troupe-vcs-git` with `git rev-parse --is-inside-work-tree`, with a fix that names
  `git init` (design D7). Verify with tests for each vcs spec scenario: outside any repository, a subdirectory of a
  work tree with no commits, a `.git` directory, and a bare repository.

## 2. Config's recording path, shared

- [x] 2.1 Move `config_set`'s recording body (lock, plan, stage, record, move) into one function that takes the
  operations, an optional identity and the reason, and have `config-set` call it (design D3). Verify that the
  existing config and config-files suites pass unchanged.

## 3. The example actor

- [x] 3.1 Add `troupe.core.audition`: the actor name `lead`, and an audition per runner (the actor's values and the
  example direction) for `claude-code` and `scripted`, as design D6 gives them. Verify with tests that every runner
  in `interim.RUNNERS` has an audition, and that each audition's actor passes the actor schema and its runner's
  options schema (config spec, "The audition's config is valid").
- [x] 3.2 Have the scripted audition's `init` event read the installed scripted runner's version from its package
  metadata. Verify with a test that compares it with `importlib.metadata.version`.

## 4. The init command in the core

- [x] 4.1 Add `init-request.schema.json` and `init-result.schema.json` to `protocol/schemas/client/` (request:
  optional `audition` with optional `runner`, and optional `rehearse`. Result: files, optional change and entries,
  optional actor, steps, notices), and the matching message types. Verify that the protocol round-trip and
  random-generation tests cover `init`, and that a request with `path` is refused with `client.invalid-request`.
- [x] 4.2 Add `theatre.exists` to `troupe.core.errors` (exit 1) with its details schema. Change
  `theatre.not-found`'s fix to name `troupe init`. Verify with the cli spec's "No theatre" scenario test and the
  error-schema test.
- [x] 4.3 Implement `init` in a core module, registered with the dispatcher. It checks in design D2's order, makes
  `.troupe/` with `ensure_git_files`, records the audition through task 2.1's function with the identity resolved
  up front, and removes the `.troupe/` it made if it fails before recording. Verify with core tests for each
  scenario: a fresh repository, a subdirectory, a theatre here, a theatre above, a `.troupe` file, no repository,
  an unknown runner, no identity (nothing made in each refusal), one `Config.Changed` with a command cause, and none
  for plain init.
- [x] 4.4 Build the next steps as data (design D8): commit when the adapter has commits, the local-stage step only
  when policy doesn't allow it (read through the policy seam), and perform. Verify with tests for policy unset, set
  to `true`, and malformed (refused as `perform` refuses it), and that plain init has no perform step.
- [x] 4.5 Implement the rehearsal: steps 1 to 4 of design D2, reporting the files and entries it would write, with
  no store opened and nothing made. Verify with tests that a rehearsed audition makes no `.troupe/`, and that a
  rehearsal where a theatre exists refuses with `theatre.exists`.
- [x] 4.6 Add a failure-injection test: recording fails after `.troupe/` is made. Verify that `.troupe/` is gone
  afterwards and a second `init` succeeds.

## 5. troupe init on the command line

- [x] 5.1 Add `troupe init` with `--audition`, `--runner <runner>` and `--rehearse`. The session's theatre is the
  working directory, and `--runner` without `--audition` is refused with `usage.missing-argument` naming
  `--audition` (design D4). Verify with CLI tests for each cli spec scenario under "Init's audition runner is named
  with --runner", and that the CLI's request validates against `init-request.schema.json`.
- [x] 5.2 Render the result: the theatre and files, the actor and runner, and the steps as commands to copy
  (`git add .troupe`, `git commit`, `export` or `$env:` by platform, `troupe perform lead --direction "..."`). Add
  the Claude Code note and the pointer to `.troupe/actors/lead.md` for `claude-code`. The rehearsal shows "would"
  and exits 3. Verify with CLI tests for both policy cases, the scripted and Claude Code renderings, and the
  rehearsal's exit code. Check that the global flags' placement test covers `init`.
- [ ] 5.3 Add an end-to-end test on all three platforms. In a fresh git repository, run `troupe init --audition
  --runner scripted`, then run each printed step as printed (the commit, the policy variable, the perform). Verify
  that the perform ends `succeeded` with its effect check passed. This is the issue's offline "done when".
- [x] 5.4 Add a test that `troupe init --rehearse` and `troupe init --audition --rehearse` leave the directory
  byte-for-byte unchanged, and that `troupe init` then `troupe status` succeeds.

## 6. Docs

- [x] 6.1 Update `docs/prompt-book/cli.md`: add `troupe init` to the commands, replace "troupe never creates one for
  you", and regenerate the reference with `uv run scripts/docs_reference.py`. Fix the stale "scripted is the only
  one so far" while there. Verify that the docs check passes, including the CLI examples that run as written.
- [x] 6.2 Add an "audition" row to `docs/prompt-book/glossary.md`, beside rehearsal. Verify with the docs check.
- [x] 6.3 Correct the sentences in `docs/opening-night/first-theatre.md` ("Make the theatre": use `troupe init`,
  and drop "There's no setup command yet") and `docs/the-company/theatres.md` that say troupe never makes a theatre.
  Leave the walkthrough rewrite to #234. Verify with the docs check and a grep for "mkdir .troupe" that finds
  nothing in `docs/`.

## 7. Integration checks

- [x] 7.1 Run `uv run scripts/check.py` and verify it passes (ruff, mypy --strict, import contracts, tests).
- [x] 7.2 Check the Claude Code path by hand, with Claude Code installed and logged in. In an empty git repository,
  run `troupe init --audition`, then each printed step. Verify that the perform ends `succeeded` (the issue's
  "done when"), and record the commands and output in the PR.
- [x] 7.3 Run `openspec validate init-and-audition --strict` and verify it passes.

## Workflow follow-up

- Open a draft PR that closes #233, act on Claude's review of the last push, then mark it ready.
- Archive the change on the branch before the owner merges.
- After the merge, comment on #233 with the PR and the archived change, and check that its card is Done.
