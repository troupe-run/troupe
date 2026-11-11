# Tasks

Each group lands its own tests and docs. Each new test is run against the code before its group's change and seen to
fail where it should (the count goes in the task), and `uv run scripts/check.py` passes before each commit.

## 1. A local index the tests can install from (design D5)

- [ ] 1.1 Add a test helper in `scripts/tests/workspace/` that serves a minimal simple index from a thread on
  `127.0.0.1` (port 0): one hand-built pure-Python wheel with a console script, a page for its package that can be
  told to answer a status (such as `503` or `404`) for its first N requests, and a count of the requests each path
  received; it stops in teardown. Verify with a test that `uv tool install --no-cache --index-url <index>` installs it
  into a scratch tool directory and the console script runs.

## 2. The retries and the caller's value (design D1–D3)

- [ ] 2.1 Add unit tests in `scripts/tests/workspace/test_install_check.py` that the check's install environment
  carries `UV_HTTP_RETRIES` as the named constant when it's absent, the caller's value unchanged when it's present
  (`1`, `""` and `abc`), and the tool directories either way; see them fail on main (count).
- [ ] 2.2 Add the index tests from design D5 through the check's own `run` and environment: four `503`s then served
  installs (and the same install with `UV_HTTP_RETRIES=3` fails, showing four failures are past uv's default); a
  `404` fails naming the install step and uv's output after exactly one request for the page; an index that always
  fails, with the caller's `UV_HTTP_RETRIES=1`, fails naming the step after exactly two requests; `abc` fails with
  output naming `UV_HTTP_RETRIES` and `abc`. Each test's name says what its body checks. See the first fail on main
  (count).
- [ ] 2.3 Add `HTTP_RETRIES = 6` to `scripts/install_check.py` beside `INSTALL_TIMEOUT`, with a docstring giving what
  it's for and how it was sized (design D2), and add it to the environment the check gives uv only when
  `UV_HTTP_RETRIES` is absent (design D3), so both `uv tool install` runs get it. Mention it in the module docstring.
  Verify 2.1 and 2.2 pass, and record the first-scenario test's time.
- [ ] 2.4 In `contributing/releasing.md`'s install check paragraph, say that the check retries a package index for
  about two minutes before an install fails (`HTTP_RETRIES` in `scripts/install_check.py`), so a failed leg that names
  a network fault has already outlasted a short outage. Verify the docs check passes (`uv run scripts/check.py`).

## 3. The whole check

- [ ] 3.1 Run `uv run scripts/install_check.py --ref HEAD` locally and see it pass, and run it once with
  `UV_HTTP_RETRIES=abc` and see it fail at the install step naming the variable. Then run the full
  `uv run scripts/check.py` and see it pass.
- [ ] 3.2 Once the pull request is marked ready, verify CI's install check passes on all twelve legs on its head, and
  record each leg's install check step time against #372's run 42919100829 to confirm the change adds nothing when the
  index answers.

## Workflow follow-up

- Open the draft pull request with `Closes #375`, act on Claude's review, mark it ready, and archive the change on the
  branch before the owner merges it.
- After the merge, comment on #375 with the pull request and the archived change, and check the issue is closed and
  its card is Done.
