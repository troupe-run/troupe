# Tasks

## 1. Pin today's behaviour before changing it (design D6)

- [x] 1.1 Write the differential property tests first and run them against the current reader
  (`troupe.cli.values.split_path`), marked to target the new module once it exists. The first checks that any text
  with no `[`, `]`, `\` or `=` and no empty key reads as `text.split(".")`. The second checks that `".".join(p)` reads
  back as `p` for keys without `.[]=\`. Verify: both pass on main's code before any other change, and the commit
  message says so.

## 2. The path module and its error (design D1, D2, D3, D5)

- [x] 2.1 Add `config.path-malformed` to `error.schema.json` in `protocol/schemas/` and the package's copy, with
  closed, required details `text`, `offset` (integer ≥ 0) and `rule`, and give it exit code 1 in
  `troupe.core.errors`. Add its row to `contributing/config.md`'s code table. Verify: the schema tests pass, and
  `uv run scripts/check.py` shows the copies agree.
- [x] 2.2 Add `troupe.core.config_paths` (design D3 says why it isn't in `troupe.core.config`) with `parse`, `parse_prefix` (stops at the first `=` outside brackets and
  returns where) and `shown`, as D2 and D3 give them, raising `config.path-malformed` with the rule and offset for
  each refusal. Verify: a table test with one row per refusal in D2 checks the rule, the offset and that the error
  validates against the schema, and the spec's parse scenarios pass (brackets, escapes, colon, brackets around a
  plain key).
- [x] 2.3 Point task 1.1's tests at `paths.parse`/`paths.shown`, and add D6's round-trip property, where
  `parse(shown(p)) == p` for any non-empty keys from all of Unicode, and its property that `parse` only ever returns
  keys or raises `config.path-malformed`. Verify: they pass, and they fail when `shown` stops escaping `]` (checked by
  hand once, then reverted).

## 3. Show every config path through `shown` (design D3)

- [x] 3.1 Remove `troupe.core.config.changes.dotted` and use `paths.shown` at every call site in `changes.py`,
  `kinds.py` and `merge.py`, and for `config.not-resolvable` in `commands.py`. Verify: the existing config tests
  pass unchanged, and a new test gets `config set runtimes[my.rt].endpoint=…` refused and checks that the problem and
  fix name `runtimes[my.rt]` while `details.path` is `["runtimes", "my.rt"]`.
- [x] 3.2 Use `paths.shown` in `cli/config.py`'s entry and conflict lines, and in `config get`'s "Nothing is set at …"
  (show the parsed path, not the typed text). Verify: rendering tests with result data for an entry and a conflict at
  `["runtimes", "openai", "prices", "gpt-4.1", "input"]` show `runtimes.openai.prices[gpt-4.1].input`, and
  `config set actors[tester].runner=scripted` prints `actors.tester.runner`.
- [x] 3.3 Check that no config path is built by hand in `packages/troupe/src`, whether with `".".join`, `split(".")`
  or an f-string (`actors.{name}...`, `{RUNTIMES}.{name}...`). The f-string form was missed at first and found by the
  review of #324 (`runtimes.py`'s fix split `runtimes[my.rt]`). Verify: the grep lists only uses that aren't config
  paths, and `test_no_source_builds_a_config_path_with_a_name_in_an_f_string` fails on the sources before the fix
  (all 8 sites) and passes after.

## 4. Read every typed path with `parse` (design D4)

- [x] 4.1 Replace `values.split_path` with `paths.parse` for `config unset`, `config get` and `config get --resolved`.
  `_usage` takes parsed keys, not text. Verify: CLI tests for the spec's unset, get and `--resolved runtimes[openai]`
  scenarios pass, and the unset test checks the request's path is `["runtimes", "openai", "prices", "gpt-4.1"]`.
- [x] 4.2 Have `config set` find the end of each path with `paths.parse_prefix`, pass the parsed keys to `value_of`,
  and compare parsed paths in `_runner_of`. Keep "doesn't set anything" for text with no `=` outside brackets, and
  raise `config.path-malformed` first when the path can't be read. Verify: CLI tests for `'actors[a=b].runner=scripted'`
  (details path `["actors", "a=b"]`), `runtimes[my.rt]=@runtime.json`, and `actors[tester].runner=scripted` with
  options typed by the scripted runner's schema (which proves `_runner_of` matched).
- [x] 4.3 Test the spec's malformed-path scenarios through the CLI, each refused with `config.path-malformed` and
  nothing recorded, including `a..b`, which moves from `config.invalid`. Update the existing tests that expected
  `config.invalid` for an empty key. Verify: the tests pass, and the config stream is unchanged after each refusal.

## 5. Docs (design Risks)

- [x] 5.1 Document how a path is written in `docs/prompt-book/cli.md`'s `troupe config set` section: brackets, the two
  escapes, `=` inside brackets, and the example quoted for zsh, with one sentence on why brackets and quotes. Verify:
  `uv run pytest packages/troupe/tests/test_cli_docs.py` passes, and each documented command runs as written in a
  scratch theatre (output pasted in the commit message).
- [x] 5.2 Mention the bracket form in `config set`'s and `config unset`'s `--help` metavar text. Verify: `troupe config
  set --help` shows it, and the help tests pass.
- [x] 5.3 If #292 has merged, rewrite its dotted-path limit note in `docs/stagecraft/runtimes.md` to show
  `runtimes.<name>.prices[gpt-4.1]`, and add an end-to-end test that sets and unsets one model's price this way. If it
  hasn't merged, comment on #292's pull request with the bracket form, so whichever merges second makes that edit.
  Verify: the doc edit and test are in this PR, or the comment's link is in the PR description. Done: the note went to
  #317 (https://github.com/troupe-run/troupe/pull/317#issuecomment-6716861478), and #317 then merged first, so the
  edit is here, after the rebase. `docs/stagecraft/runtimes.md` sets `prices[gpt-4.1]` on its own, which its page test
  runs as written. The `prices` description in `config/runtime.schema.json` (and the models and reference generated
  from it) gives the bracket form. `test_a_model_whose_name_holds_a_dot_is_priced_changed_and_unpriced_on_its_own`
  sets, changes and unsets that one price through the CLI.

## 6. Integration

- [x] 6.1 Run the whole check. Verify: `uv run scripts/check.py` passes locally, and CI passes on Linux, macOS and
  Windows on the PR's last code commit, with the run cited here. Done: the full check passed locally before each
  commit, and after the rebases onto main (#289's `_move_fix`, #292's prices), [CI run
  42538200875](https://github.com/troupe-run/troupe/actions/runs/42538200875) passed every job (ubuntu, macos and
  windows; Python 3.12–3.15) on `fb031f77`, the last code commit. Its first attempt failed three jobs on three tests
  this change doesn't touch (the Claude Code runner's flags and a CRLF worktree test on Windows, and Ollama's
  cancel-while-streaming, which also failed on main at `4bbd57c7`); re-running them passed.

## Workflow follow-up

- Open a draft PR with `Closes #303`, act on Claude's review of the last push, and mark it ready once that review is
  clean.
- Archive the change on the branch (`openspec validate --strict` first), then ask the owner to merge.
- After the merge, comment on #303 with the PR and the archived change, and check that its card says Done.
