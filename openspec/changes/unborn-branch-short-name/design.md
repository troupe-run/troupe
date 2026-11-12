# Design

## Context

See proposal.md, Why. Today (`packages/troupe-vcs-git/src/troupe_vcs_git/__init__.py`, after #367 and #370):

- `_current()` reuses a snapshot while the token's stats match (#75, cache-vcs-state D1). Otherwise it reads HEAD
  with `_read` (born: one `rev-parse` with `--abbrev-ref=loose`) or `_read_unborn`: `symbolic-ref --quiet HEAD` (full
  name), `symbolic-ref --quiet --short HEAD` (short name), then `rev-parse --verify --quiet HEAD`.
- git-branch-cache watches every place git looks for a ref sharing the branch's name, and under the files storage
  re-reads on every call while one of them is a symbolic ref (its D1–D3). None of that changes here.

**git's rule** (`refs_shorten_unambiguous_ref`, loose mode, as `rev-parse --abbrev-ref=loose` and `symbolic-ref
--short` both call it). The rev-parse rules, in order, are `%s`, `refs/%s`, `refs/tags/%s`, `refs/heads/%s`,
`refs/remotes/%s` and `refs/remotes/%s/HEAD`. For each rule *i* the full name matches, from the last rule back to the
second, with *s* the short name that rule gives: if no earlier rule's expansion of *s* resolves to a ref, the answer
is *s*. If none qualifies, the answer is the full name. "Resolves" follows symbolic refs: a dangling one doesn't count.

**The bug.** `symbolic-ref` passes git the name `HEAD` resolved to, which lives in a buffer that resolving a symbolic
ref overwrites. The ambiguity check resolves the candidates, so a symbolic candidate replaces the name being
shortened, and the answer is cut from its target (`gone`, `heads/main`, `one2`). It's the same under both storages.

**What git can tell us, probed on git 2.56, files and reftable.**

- `rev-parse --abbrev-ref=loose` refuses an unborn ref, whether named as `HEAD` or in full.
- `show-ref --verify` misses a lower-case root ref (`.git/feature`) that git's rule counts. `show-ref --exists` and
  `git refs exists` count a dangling symbolic ref. `for-each-ref --include-root-refs` lists neither `FOO` nor `x`.
- `git -c core.warnAmbiguousRefs=false rev-parse --symbolic-full-name --revs-only --end-of-options <s>` prints the
  **first** ref `<s>` resolves to in rule order, the same rules and resolution the shortening uses, root refs
  included, or nothing. With the warning on, a name matching two refs prints nothing.
- In one `rev-parse`, the first name that doesn't resolve makes every later name a path, printed by nothing.

## Goals / Non-Goals

**Goals:**

- An unborn branch reports exactly the name `rev-parse --abbrev-ref=loose HEAD` will report once it has a commit,
  whatever refs share its name, on both ref storages, in the main worktree and a linked one.
- No more commands than today, and nothing added to a cached read.

**Non-Goals:**

- The token, the watched refs and the racy rule (git-branch-cache, #371): unchanged.
- The born read: already right.
- Reporting the bug upstream to git. Worth doing, but separate; noted in tasks as a follow-up.

## Decisions

### D1: Shorten an unborn branch's full name by git's rule, in the adapter

`_read_unborn` keeps `symbolic-ref --quiet HEAD` for the full name, which is right, and drops `--short`. It applies
the rule above to the full name, rule by rule from the last, asking git (D2) which ref each short name resolves to
first. For `refs/heads/<n>` that's at most two questions: `<n>` (rule 3), then `heads/<n>` (rule 1) only if `<n>` was
ambiguous. A HEAD naming a ref outside `refs/heads/` takes the same walk with its own rules.

*Alternatives:*
- **`rev-parse --abbrev-ref=loose` on the full name** (the issue's first option): git refuses an unborn ref.
- **Check `symbolic-ref --short`'s answer against the full name** (the issue's second): catches `gone` and `one2`,
  but `heads/main` (a tag `feature` pointing at `main`) is a valid shortening of *some* name, and there's no right
  answer to fall back to without the rule anyway.
- **Use `symbolic-ref --short` unless a symbolic ref shares the name**: needs a way to see a dangling symbolic ref
  under reftable, which no command gives, and leaves two ways to get one answer.

### D2: Which ref a short name resolves to first, from git in one command

`git -c core.warnAmbiguousRefs=false rev-parse --symbolic-full-name --revs-only --end-of-options <s1> <s2> …`, with
the short names in the walk's order (rule 3's first). Rule *i*'s *s* is ambiguous when its first match is an earlier
rule's expansion of *s*. The full name itself can't be that match: it's unborn. Any other answer, or none, means *s*
is the short name.

The order makes the one-command form safe. A name that resolves to nothing makes the later ones paths (Context), but
it's also not ambiguous, so the walk stops there and never needs the later answers. Each answer is read in order,
and a name's answer is one of its own expansions, so it can't be mistaken for another's.

`-c core.warnAmbiguousRefs=false` overrides the user's setting for this command only: with the warning on, a name
matching two refs prints nothing, which would read as "not ambiguous". The command count stays three for an unborn
HEAD the files show (`symbolic-ref`, this, `rev-parse --verify HEAD`), four otherwise.

*Alternative:* one command per candidate ref (`show-ref --verify` and the like): more commands, and none of them
agrees with git on every candidate (Context).

### D3: The differential tests compare against the name the branch has once it's born

`gits_answers` and the `Names` invariant take git's short name from `rev-parse --abbrev-ref=loose HEAD` when HEAD is
born. When it's unborn, the test makes an empty commit on the branch, reads that, then deletes the branch's ref
(`update-ref -d`), which leaves HEAD unborn again with the same refs. `Names` gains a rule that makes a symbolic ref
named after the current branch, in each shape git weighs (`refs/tags/<n>`, `refs/<n>`, root `<n>`), pointing at a
missing ref or an existing one, and works while the branch is unborn as well as born.

## Risks / Trade-offs

- [The adapter copies git's rule, so a git that changes the rule would disagree] → The differential tests compare
  against git's own `--abbrev-ref=loose` on every run, on each CI OS's git, so a change shows up as a failing test,
  not as wrong lineage.
- [D2 rests on two behaviours git's documentation doesn't state: with `core.warnAmbiguousRefs` off,
  `--symbolic-full-name` prints a name's first match in rule order (with it on, a name matching two refs prints
  nothing and still exits 0); and the first name that resolves to nothing makes every later name a path, printed by
  nothing] → A test pins both against a real repository on every CI OS (task 1.3): a name matching a root ref,
  `refs/<n>` and `refs/tags/<n>` prints the root one; with the warning on, the same name prints nothing; and a
  resolving name after one that doesn't resolve prints nothing. If a git changes either, that test fails by name,
  ahead of the differential tests.
- [`--end-of-options` (new to the adapter) or `core.warnAmbiguousRefs` behaving differently on the git a CI OS ships]
  → The same tests run on Linux, macOS and Windows, and task 3.2 records the git version each leg ran.
- [`update-ref -d` in the test oracle removes the branch's reflog] → Only in the test repository, and the property
  test doesn't read reflogs.
