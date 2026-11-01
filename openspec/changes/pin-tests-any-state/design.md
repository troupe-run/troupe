# Design

## Context

See proposal.md, "Why". Three test files build a `copy` fixture from the real repository's files and then edit it:

- `test_bundle.py` copies the root and every member's `pyproject.toml`, and edits the bundle's with `replace`, which
  asserts an exact string is present: `'    "troupe-runner-scripted",\n'`, `'    "troupe",\n'`, `'"troupe-vcs-git"'`.
- `test_pin_bundle.py` copies the pyprojects, `release-please-config.json` and the manifest, sets every member to
  0.1.0 and the bundle to 0.0.0, and gives each member a first-release changelog. Its docstring says this is the state
  merging the first release pull request leaves, but the bundle's dependencies and the config's `exclude-paths` are
  whatever the repository holds. On #228 they're already pinned and removed, so `pin_bundle.moves` returns nothing.
- `test_release_config.py` copies the files `release_config.problems` reads, parametrized `as-is` and `released`
  (#188, design D3). Its missing-manifest test pops `plugins/runner-scripted` from the manifest; with the bundle
  pinned, `_pin_problems` also (correctly) names the pin to a member the manifest now gives 0.0.0.

On #228's head the failures are exactly the 11 the issue lists. Two more tests in `test_pin_bundle.py`,
`test_the_first_pin_pins_every_member_and_changes_nothing_else` and `test_crlf_line_endings_are_kept`, pass there
only because nothing moves: the first compares the file with itself, the second checks the line endings of a file it
never wrote.

The pinning step's own functions are the real definition of "pinned": `pin_bundle.moves` and `pin_bundle.apply`
(which pins each released member at its manifest version and removes the bootstrap line), and `release_config.pin`,
`requirement_name` and `bundle_member`.

## Goals / Non-Goals

**Goals:**
- Every test in the three files passes on `main` before the first pin, on #228, and after every later pin.
- A test that assumes the bundle is bare, or pinned, fails in the ordinary check on `main` rather than first on a
  pinning pull request.
- No first-pin test can pass without a pin happening.

**Non-Goals:**
- Changing `bundle.py`, `pin_bundle.py`, `release_config.py`, or any message they return.
- `test_the_bundle_names_each_dependency_bare_or_pinned_at_a_tag` and the tests that run on `REPO` itself: they read
  the real files on purpose and pass in either state.
- Other test files. `test_install_check.py`, `test_install_docs.py` and the release workflow tests passed on #228
  (only the three files failed), and none of them edits the bundle's dependencies.

## Decisions

### D1. One shared helper module builds each state

A module beside `conftest.py`, `scripts/tests/bundle_state.py` (where mypy's `mypy_path` and pytest's `sys.path` already find test helpers), with two functions on a copy's root:

- `unpinned(root)`: the state before the first pin. Every dependency of the bundle on a workspace member is rewritten
  to its bare name, the bundle's entry in the config gets its bootstrap line back
  (`      "exclude-paths": ["<bundle>"],` on its own line after the entry's `"component"` line, the one form
  `pin_bundle._unexcluded` can remove), and when the copy has a manifest, the bundle's version in it is `0.0.0`.
  The three go together because that's the only consistent pre-pin state: the check fails an exclusion kept after the
  bundle released.
- `pinned(root)`: the state the pinning step leaves, built by running it, `pin_bundle.apply(root,
  pin_bundle.moves(root))`. Every member released in the manifest is pinned at that version, unreleased ones stay
  bare, and the exclusion is gone. It needs the config and manifest, so every copy that uses it copies them.

Each edits text in place (bytes in, bytes out, as `pin_bundle` does), finds dependency lines by
`release_config.requirement_name` rather than by an expected string, and takes the bundle's path from
`release_config.bundle_member`, so no member path is written as a literal (memory: a `packages/<name>` literal in a
shared module widens which suites the check runs).

*Alternative:* each file builds its own state inline. Rejected: three slightly different definitions of "unpinned"
is how #229 happened. *Alternative:* `pinned` writes pins with `release_config.pin` directly. Rejected: running the
step is what makes the copy match what a pinning pull request really leaves, and it's one line.

### D2. `test_bundle.py` and `test_release_config.py` run on both states

Both `copy` fixtures gain a `bundle` dimension, `unpinned` and `pinned`, applied right after copying. For
`test_release_config.py` it is applied before the existing `released` step, so the four cases are the repository
before and after the first pin, each as-is and after a release (`release` already removes every `exclude-paths`, as
the bundle's first release follows its first pin).

`test_the_copy_of_the_real_files_has_no_problems` must pass in every combination, which checks that each built state
is one the check accepts. Its name stops being accurate once the copy is edited, so it becomes
`test_the_copy_has_no_problems`, with the states in its docstring.

*Alternative:* leave the fixtures as they are and only fix the 11 tests. Rejected for the same reason as #188's D3:
it fixes these failures, but the next test written against `main` can assume "pinned" just as easily, and nothing
would show it until the state changes again.

### D3. `test_bundle.py` edits a dependency by name

`replace` with a fixed bare line becomes two small helpers built on `requirement_name`: one drops the line of the
dependency named `name`, one sets it to a given requirement. The non-member test adds `"troupe-vcs-svn"` as a new
line after `dependencies = [`. The pinned-dependency test pins `troupe-vcs-git` at `0.1.1` explicitly, whatever it
was, so under both states it checks that a pin counts. The tests that edit `[project.scripts]` or core's
dependencies keep `replace`: those lines don't change with pinning.

### D4. `test_pin_bundle.py`'s copy is always unpinned

Its fixture calls `unpinned` after copying, which makes its docstring true. It doesn't gain a `pinned` dimension:
its cases already describe a sequence from the first pin (`pin_all` then a `release`), so the starting state is part
of each case, not a variable. The `before` text of `test_the_first_pin_removes_only_the_bootstrap_exclusion` then
holds the bootstrap line wherever the test runs.

### D5. The first-pin tests prove something moved

`test_the_first_pin_pins_every_member_and_changes_nothing_else` asserts that the moves name every member but the
bundle and that `expected != before`, and `test_crlf_line_endings_are_kept` asserts the file changed. With D4 these
hold anyway; the assertions are what stop a future copy from making them vacuous again
(learned: a test name that overclaims is worse than no test).

### D6. The missing-manifest test makes its member bare

A member missing from the manifest is a new member, and a new member is bare until it releases. The test sets
`troupe-runner-scripted`'s dependency to its bare name in the copy before popping it from the manifest, so its one
expected message holds under both states.

*Alternative:* under `pinned`, expect the check's second message too ("pins troupe-runner-scripted at 0.1.0, but …
gives 0.0.0: … name it bare"). Rejected: it would enshrine advice that's wrong for that state (the fix is the
manifest entry, not unpinning) in a test about a different message. The message itself is out of scope (proposal,
"Impact").

## Risks / Trade-offs

- [The helper could build a state no real commit has] → each state must pass `test_the_copy_has_no_problems` in
  both files (D2), and `pinned` is built by the pinning step itself (D1).
- [The fix could pass on `main` and still fail on #228] → verify it there before opening the pull request: run the
  three fixed files in a throwaway worktree of #228's head under the scratchpad, which is the merge CI will run.
- [Restoring the bootstrap line by text depends on the config's layout] → the helper asserts the entry's
  `"component"` line is found exactly once and fails naming the file otherwise, rather than writing a config the
  pinning step would refuse.
