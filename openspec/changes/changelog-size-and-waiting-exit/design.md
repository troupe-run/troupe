# Design

## Context

- The size gate is delivered from troupe-run/infrastructure (`scripts/quality_gates.py`), and reads each repository's own
  limits and `exclude` globs from `quality-gates.toml`. troupe's `[size] exclude` already leaves out
  `**/fixtures/**`, `openspec/changes/archive/**` and `uv.lock`, because none of them is reviewed as code.
- `troupe perform` prints a settle hint on standard error at a worktree run's end (`_settle_hint` in
  `packages/troupe/src/troupe/cli/commands.py`). For a waiting run it says today: "run X waits at its gate for
  director[ because ...]. Its changes are in its worktree, .... See them with `troupe diff X`, then `troupe approve X`
  or `troupe reject X`." Standard output says `run <id> succeeded`, and the exit code is 4. A person who sees only
  the exit code, or a shell `&&`, reads that as failure.
- A run reaches a gate only when it `succeeded` with a captured diff (`gate.reaches_gate`), so a waiting run has
  always succeeded.
- The CLI reference's exit-code table is generated from `ExitCode`'s docstrings, and already says 4 means the run
  succeeded and its work waits.

## Goals / Non-Goals

**Goals:**
- #533, and every later release, passes the size gate whatever the size of a changelog.
- A newcomer reading perform's output, or the walkthrough, can't mistake exit 4 for failure.

**Non-Goals:**
- Changing exit 4 itself (owner, 2026-11-27: keep 4).
- Splitting or trimming any changelog. Changing infrastructure's delivered gate, or other repositories' limits.
- Changing `troupe init`'s printed next steps. They already say the run waits at its gate for you. The walkthrough's
  commands are checked against them, and that comparison is about commands, not prose.

## Decisions

**D1. Exclude `**/CHANGELOG.md`, not a `[size.allow]` ceiling.** A ceiling postpones the failure by the margin, and
`[size.allow]` expects an issue that splits the file, which release-please can't do. The gate is there so a review
can read each changed file whole. Claude's review doesn't run on release pull requests, and no person edits a
changelog. The glob covers every component's changelog, including the protocol's (22 KiB today) and those of any
future package.

**D2. The waiting hint leads with success and gives exit 4's meaning in words.** New text:
"troupe: run X succeeded, and its work waits at its gate for director[ because ...]: exit 4 means waiting for
director, not failure. Its changes are in its worktree, .... See them with `troupe diff X`, then `troupe approve X` or
`troupe reject X`." This is the only place perform's exit code gets explained. It names the role rather than "you",
because the role may be held by someone else. Since only a succeeded run can be waiting (Context), the hint can say
"succeeded" without checking the outcome again. The existing substring "waits at its gate for director", which tests
and docs rely on, stays.

**D3. The walkthrough says it in one plain sentence, and a test pins it.** Line ~101 of
`docs/opening-night/first-performance.md` changes from "exits 4 rather than 0" to say that exit 4 means the run
succeeded and its work waits for you, and that it isn't a failure. A docs unit test checks that the page says so and
that the generated exit-code table gives 4 as `WAITING` with "succeeded".

## Risks / Trade-offs

- A changelog can now grow without limit. Accepted: it's generated, it isn't reviewed as code, and history belongs in
  it.
- A longer hint line. It stays one line on standard error, and standard output (`run <id> succeeded`) is unchanged,
  so scripts that read standard output still work.
