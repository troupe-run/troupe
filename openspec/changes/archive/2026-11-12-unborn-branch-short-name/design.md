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
- `rev-parse --symbolic-full-name` **follows a symbolic ref**: for a tag `feature` pointing at `refs/heads/main` it
  prints `refs/heads/main`, not the ref the name matched. Found while applying (2026-11-12), after an earlier D2 had
  relied on reading the first match from it.
- `for-each-ref --format=%(refname) <patterns>` lists each ref that resolves, a symbolic ref by its own name, and
  leaves out a dangling one, on both storages: git's rule for every candidate under `refs/`. A pattern also matches
  refs below it, so only exact names count.
- With ambiguity warnings on, `rev-parse --symbolic-full-name --revs-only` prints a name that one ref matches (a
  symbolic ref's target) and nothing when two or more do, or none, and exits 0 either way. Root refs count, and git
  makes upper-case root symbolic refs (`FOO`, `FOO_HEAD`); it refuses lower-case ones.
- Root refs are files under the files storage. Under reftable they're in the tables and a single level, so a root
  ref with a `/` in its name (`heads/<n>`) exists only under the files storage.

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
the rule above to the full name, rule by rule from the last, asking git (D2) which of each short name's earlier
expansions are refs. For `refs/heads/<n>` that's two levels: `<n>` (rule 3), then `heads/<n>` (rule 1) only if `<n>`
was ambiguous. A HEAD naming a ref outside `refs/heads/` takes the same walk with its own rules.

*Alternatives:*
- **`rev-parse --abbrev-ref=loose` on the full name** (the issue's first option): git refuses an unborn ref.
- **Check `symbolic-ref --short`'s answer against the full name** (the issue's second): catches `gone` and `one2`,
  but `heads/main` (a tag `feature` pointing at `main`) is a valid shortening of *some* name, and there's no right
  answer to fall back to without the rule anyway.
- **Use `symbolic-ref --short` unless a symbolic ref shares the name**: needs a way to see a dangling symbolic ref
  under reftable, which no command gives, and leaves two ways to get one answer.

### D2: Which candidate refs exist, from git, and a refusal where git can't tell

Revised while applying, with the owner (2026-11-12): the first version read each short name's first match from one
`rev-parse --symbolic-full-name`, which follows symbolic refs (Context), so a tag `feature` pointing at an existing
branch read as "not ambiguous".

- **Candidates under `refs/`**, for every level of the walk: one `for-each-ref --format=%(refname)` with their exact
  names as patterns, keeping only exact matches. It lists symbolic refs by their own names and leaves out dangling
  ones, as git's rule does.
- **A candidate at the top of the git directory** (`<n>`, then `heads/<n>`), asked about only when the walk gets to
  it, which is when no candidate under `refs/` already made the name ambiguous:
  - Under the files storage, if no file of that name is in the worktree's git directory or the common one, it isn't
    a ref and no command runs. That's the usual case.
  - Under reftable, a name with a `/` can't be one, and no command runs.
  - Otherwise git counts: `git -c core.warnAmbiguousRefs=true rev-parse --symbolic-full-name --revs-only
    --end-of-options <name>` prints something for one matching ref and nothing for two or more. The full name can't
    be among them (it's unborn), and `for-each-ref` already said how many of the name's other expansions (*k*) are
    refs. With *k* = 0, the root ref exists if anything is printed. With *k* = 1, it exists if nothing is.
  - With *k* ≥ 2, nothing is printed either way, so git's answers can't decide. The read is refused with
    `vcs.short-name-undecided`, naming the branch, the name and the refs. The fix is to make a commit on the branch,
    after which git names it itself, or to delete one of those refs. This is the owner's earlier choice to refuse
    where the check can't be exact. Under the files storage it needs a hand-made `heads/<n>` at the top of the git
    directory and two of a tag, branch or remote-tracking ref named `heads/<n>`.

`-c core.warnAmbiguousRefs=true` overrides a user's `false`, which would make git print the first match instead of
nothing.

**Every root candidate in one command** (owner, 2026-11-12, to keep within five): `git -c core.warnAmbiguousRefs=true
rev-parse --revs-only --symbolic-full-name --git-dir <n> --git-dir heads/<n>`, with only the candidates that may be
root refs. The walk collects them before asking: it goes on past a candidate that may be one, and stops at a level
nothing can make ambiguous. `rev-parse` runs options where they stand, so each `--git-dir` prints the git directory
before the name after it. The first line is that separator, and the lines between separators are one name's
answer. An ambiguous name still counts as a revision, so the names after it are still asked. A name that resolves to
nothing makes the rest paths, printed by nothing, but such a name isn't ambiguous, so the walk never needs a later
answer. Options can't follow `--end-of-options`, so a name beginning with `-` is asked on its own after one. That's a
hand-made branch, which git won't create, at one command per candidate.

**Commands**: an unborn HEAD the files show takes three (`symbolic-ref`, `for-each-ref`, `rev-parse --verify HEAD`),
and four when a file at the top of the git directory may be a root candidate. Otherwise it takes four, the failed
`rev-parse` first, and five with the root candidates. Under reftable that's five whenever the branch's name has no
`/`, since no file shows whether a root ref is there.

*Alternatives:* `show-ref --verify`, `show-ref --exists`, `git refs exists` and `for-each-ref --include-root-refs`
each disagree with git's rule on some candidate (Context). Reading root ref files in the adapter would copy git's
per-worktree and storage rules, which git-branch-cache chose not to do.

**The spec**: the requirement is removed and added again as "The git adapter reads the branch and HEAD in one
command once HEAD has a commit". Its scenario "Any other unborn HEAD is read in four commands" becomes false under
reftable, and OpenSpec refuses a MODIFIED block that drops or renames a scenario.

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
- [D2 rests on behaviours git's documentation doesn't state: `for-each-ref` lists symbolic refs by their own names
  and leaves out dangling ones; `--symbolic-full-name` follows symbolic refs; with warnings on, two matches print
  nothing and exit 0, root refs counted] → Tests pin each against a real repository on both storages, on every CI
  OS (task 1.3), with the git version in the failure, so a different git fails by name before the differential tests.
- [`--end-of-options` (new to the adapter) or `core.warnAmbiguousRefs` behaving differently on the git a CI OS ships]
  → The same tests run on Linux, macOS and Windows, and task 3.2 records the git version each leg ran.
- [`update-ref -d` in the test oracle removes the branch's reflog] → Only in the test repository, and the property
  test doesn't read reflogs.
