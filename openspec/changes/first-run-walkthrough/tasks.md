# Tasks

## 1. init's allow step says to set it once, in the shell profile

- [x] 1.1 Add tests to `packages/troupe/tests/test_cli_init.py` for the cli spec's two new scenarios: on Linux and
      macOS the allow step's note names `~/.zshrc` and `~/.bashrc`, says to add it once and that it then applies to
      every theatre, and doesn't say "each shell"; on Windows (the shell choice patched to PowerShell) the line is the `$env:` form and
      the note names `$PROFILE`. Verify they fail against today's note.
- [x] 1.2 Change `_step_notes` in `packages/troupe/src/troupe/cli/init.py` to name the profile for the platform, chosen
      beside `_allow_line` so the line and note share one platform check (design D5). Verify the 1.1 tests and the rest
      of `test_cli_init.py` pass, and `mypy --strict` passes with `--platform win32` too.
- [ ] 1.3 Add a test for the cli scenario "The character is changed through config": `init --audition` names
      `troupe config set actors.lead.character=@<file>` and not "edit it", and running that command with a file, then
      `perform lead --rehearse`, isn't refused and `config get` shows the file's text. Verify it fails today.
- [ ] 1.4 Change the character line in `render_init` to print the `config set` command (design D8). Verify the 1.3 test
      and the rest of `test_cli_init.py` pass, and update `docs/prompt-book/cli.md` if its init entry says to edit the
      file.

## 2. The first-run walkthrough leads with Claude Code

- [ ] 2.1 Write the new tests in `packages/troupe/tests/test_user_docs_pages.py` before the page: the Claude Code
      walkthrough runs as written with the stand-in `claude` in a repository with a commit (`init --audition`, commit,
      allow, `perform lead --direction`, then `diff`, `accept`, `status`, `logs`); the page's commit and allow lines are
      the ones `init --audition` prints (design D1); the uncommitted-changes notice block matches what `perform` writes
      after a change, with the count and commit as wildcards (D2); the allow section names `~/.zshrc`, `~/.bashrc`, the
      PowerShell profile and both line forms, and `perform` is refused without the variable (D5). Verify each fails
      against today's page.
- [ ] 2.2 Rewrite `docs/opening-night/first-performance.md`: the walkthrough from `troupe init --audition` (D1), the
      notice and why a run starts from the latest commit (D2), the permission in the shell profile (D5), reviewing and
      reading back. Verify the 2.1 tests pass.
- [ ] 2.3 Add the offline section (D3): a new repository, `troupe init --audition --runner scripted`, the same steps. Add
      a test that runs it as written with no `claude` on `PATH` and gets `run <id> succeeded`. Verify it passes.
- [ ] 2.4 Add the "define your own actor" section (D4): a second Claude Code actor from `claude.json` with
      `troupe config set` and a character in `.troupe/actors/<name>.md`, with the options notes moved from
      "Run Claude Code instead", which goes. Rework the existing stand-in test to run it as written. Verify it passes,
      and no test still reads `hello.json` or the `tester` walkthrough.

## 3. The theatre and install pages

- [ ] 3.1 Rewrite `docs/opening-night/first-theatre.md` to lead with `troupe init`: what it refuses, what it writes,
      what `--audition` adds (`actors/lead.yaml` and `actors/lead.md`), and drop "Config, when it comes". Verify the docs
      check's link, front matter and vocabulary tests pass.
- [ ] 3.2 Rearrange `docs/opening-night/install.md` (D6): uv and where to get it, the latest release's command between
      the unchanged markers, `troupe --version` and the `update-shell` hint first; other releases, `main`, a commit and
      `--no-sources` below. Verify `scripts/tests/workspace/test_install_docs.py` and the Python-versions test pass.

## 4. Integration

- [ ] 4.1 Run `uv run scripts/check.py` and verify it passes.
- [ ] 4.2 Follow the new pages by hand from a fresh install of this branch with a real, logged-in Claude Code, in a
      repository with uncommitted changes: `init --audition`, a character of your own set through config, your own
      direction, and the notice shown. Then the offline path. Record the result in the PR description.

## Workflow follow-up

- Open the draft PR with `Closes #234`, act on Claude's review, mark it ready, archive on the branch, and ask the owner
  to merge.
- After the merge, comment on #234 with the PR and the archived change, and check its card says Done.
