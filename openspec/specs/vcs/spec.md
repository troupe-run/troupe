# vcs Specification

## Purpose

The version-control port troupe reads the working tree's state through, so the event store and lineage work the
same whether a theatre uses git or no version control at all.

## Requirements

### Requirement: VCS state is read through an adapter
troupe SHALL read version-control state only through a VCS adapter. The adapter SHALL report the adapter's name,
the current branch (or none), HEAD (or none), whether a theatre-relative path is committed, and the configured
identity (or none).

#### Scenario: Two adapters, one behaviour
- **WHEN** the event store's tests run with the git adapter and with the plain filesystem adapter
- **THEN** every behaviour that doesn't depend on branches passes with both

### Requirement: The git adapter
The git adapter SHALL report the checked-out branch (none when HEAD is detached), the HEAD commit (none before the
first commit), whether a path is in HEAD or the index, and the theatre's `user.email` (none when unset or empty).

#### Scenario: A fresh repository
- **WHEN** the theatre is a git repository with no commits
- **THEN** the adapter reports the branch name and no HEAD

#### Scenario: Detached HEAD
- **WHEN** HEAD is detached
- **THEN** the adapter reports no branch and the HEAD commit

#### Scenario: A staged but uncommitted file
- **WHEN** an event file has been staged with `git add` but not committed
- **THEN** the adapter reports it as committed, because it no longer travels with a branch switch

### Requirement: The plain filesystem adapter
The plain filesystem adapter SHALL report no branch, no HEAD and no identity, and SHALL report every path as
committed.

#### Scenario: No version control
- **WHEN** the theatre uses the plain filesystem adapter
- **THEN** every event is read, and none is left out as being from another branch

### Requirement: Each adapter declares its environment policy
Each VCS adapter that runs commands SHALL declare the environment policy they run with, as a named default in one
place. The git adapter's policy SHALL pass what git needs to find its configuration, credentials and SSH agent, and
SHALL exclude git's repository-location variables. The plain filesystem adapter runs no commands and SHALL declare
no policy.

#### Scenario: Git finds the user's global configuration
- **WHEN** `user.email` is set only in the user's global git configuration, and the git adapter reads the
  configured identity
- **THEN** it reports that email

#### Scenario: troupe runs inside a git hook
- **WHEN** troupe runs with `GIT_DIR` and `GIT_WORK_TREE` set to another repository, as they are inside a hook
- **THEN** the git adapter still reads the theatre's own repository

#### Scenario: Unrelated variables never reach git
- **WHEN** troupe's environment holds a variable outside git's policy, such as `AWS_SECRET_ACCESS_KEY`
- **THEN** git's environment doesn't contain it

#### Scenario: The exclusions keep up with git
- **WHEN** the installed git lists its repository-location variables
- **THEN** every one of them is excluded by the git adapter's policy

### Requirement: Calls to git are bounded and fail clearly
A call to git SHALL time out after a named setting's limit. A missing `git`, a timeout, or a git failure SHALL fail
with an error naming what was run, in which directory, and the fix. It SHALL NOT wait silently.

#### Scenario: git is not installed
- **WHEN** the git adapter is used and `git` isn't on the path
- **THEN** the command fails with an error that says git wasn't found and how to fix it

#### Scenario: git hangs
- **WHEN** a git call doesn't finish within its timeout
- **THEN** the command fails with an error naming the call and the timeout

### Requirement: The branch token changes whenever the branch or HEAD moves
Each VCS adapter SHALL give a branch token: a value that is cheap to compare. It SHALL change whenever the checked-out
branch, HEAD, or what is committed changes. That covers a change made by this process or any other, and in the git
adapter it SHALL hold with either ref storage (files or reftable), with reflogs on or off, and in a linked worktree.
Reading the token SHALL run no command while nothing has moved.

#### Scenario: A commit changes the token
- **WHEN** a commit is made in the theatre, including an empty commit, with reflogs on or off, with either ref
  storage
- **THEN** the token differs from the one read before the commit

#### Scenario: Moving HEAD without a commit changes the token
- **WHEN** the branch is switched (including to a branch with the same tree), HEAD is detached, or HEAD is reset with
  `reset --soft`, `--mixed` or `--hard`, with reflogs on or off, with either ref storage
- **THEN** the token differs from the one read before

#### Scenario: Another worktree moves the checked-out branch
- **WHEN** a process in another worktree of the same repository moves the branch this theatre has checked out
- **THEN** the token differs from the one read before

#### Scenario: Refs are packed
- **WHEN** `git pack-refs --all` moves the checked-out branch's ref into `packed-refs`, and the branch then moves
- **THEN** the token differs from the one read before the move

#### Scenario: Nothing moved
- **WHEN** the token is read twice with no git operation in between
- **THEN** both reads are equal and the second runs no command

### Requirement: The git adapter reads the branch and HEAD only when they may have moved
The git adapter SHALL report the branch and HEAD without running a command while its token is unchanged since it last
read them. It SHALL report exactly what git would report at the time of the call: a cached value SHALL be used only
while the token says nothing has moved. The branch SHALL be reported in the same form as before this requirement
(git's short name).

#### Scenario: Repeated reads cost nothing
- **WHEN** the branch and HEAD are read many times with no git operation in between
- **THEN** git commands run only for the first read

#### Scenario: Cached answers match git's after any sequence of operations
- **WHEN** any sequence of commits, switches, detaches, merges, resets, branch renames, ref packing and moves from
  another worktree runs, with either ref storage and reflogs on or off
- **THEN** after each operation the adapter reports the same branch and HEAD as an adapter that caches nothing

### Requirement: A state read at a racy time is read again
When the git adapter reads the branch and HEAD while one of the files its token watches was modified within a window,
it SHALL NOT reuse that answer, even when the token compares equal: the next call SHALL read again. The window SHALL
be longer when the watched files' timestamps are whole seconds, and each window SHALL be a named setting.

#### Scenario: A read just after a git operation is not reused
- **WHEN** the branch and HEAD are read within the window after a watched file was modified, and read again
- **THEN** the second read runs git again

#### Scenario: A read after the window is reused
- **WHEN** the branch and HEAD are read when every watched file was last modified before the window, and read again
  with nothing moved
- **THEN** the second read runs no command

#### Scenario: Whole-second timestamps get the longer window
- **WHEN** every watched file's timestamp is a whole second, as on a file system with coarse timestamps, and the
  branch and HEAD are read later than the shorter window but within the longer one
- **THEN** the next read runs git again

### Requirement: The VCS port can make, diff, apply and remove worktrees
The VCS port SHALL offer the operations a worktree run needs: list the files that match HEAD in the theatre, make a
worktree at a commit with HEAD detached, capture a worktree's changes against a commit as a binary diff with given
paths left out, check and apply a diff to the theatre's working tree all or nothing, and remove a worktree. An adapter
that can't SHALL refuse each of them with `vcs.worktrees-unsupported`.

#### Scenario: The plain filesystem adapter
- **WHEN** a worktree is asked for from the plain filesystem adapter
- **THEN** it is refused with `vcs.worktrees-unsupported`, naming the adapter

### Requirement: The git adapter snapshots the shared repository's state
The git adapter SHALL give a snapshot of the state every worktree shares: each ref and the object it points to, the
stash included, a hash of each config file the repository reads (its common and per-worktree config), and a hash of
each file in its effective hooks directory, wherever `core.hooksPath` puts it. Comparing two snapshots SHALL name each
ref, config file and hook that was added, changed or removed. The run's own worktree registration SHALL NOT count as
a change.

#### Scenario: A tag between two snapshots
- **WHEN** a tag `v0` is made between two snapshots
- **THEN** the comparison names `refs/tags/v0` as added, and nothing else

#### Scenario: Making a worktree changes nothing shared
- **WHEN** a snapshot is taken, a run's worktree is made, and another snapshot is taken
- **THEN** the comparison is empty

### Requirement: The git adapter's worktrees are registered with git and leave its refs alone
The git adapter SHALL make each worktree with `git worktree`, detached at the commit asked for, creating no branch and
moving no ref. Removing it SHALL remove its directory and its registration, and SHALL succeed when the directory was
already deleted by hand.

#### Scenario: No branch is made
- **WHEN** the git adapter makes a worktree and then removes it
- **THEN** `git branch --list` and `git worktree list` show what they showed before

#### Scenario: A worktree deleted by hand
- **WHEN** a run's worktree directory was deleted by hand and the worktree is then removed
- **THEN** removal succeeds and git no longer lists the worktree

### Requirement: The git adapter's diff is git's normalised binary diff
The git adapter SHALL capture a worktree's changes as `git diff --binary` between the worktree's starting state (a tree
written from it once it is filled, its baseline) and its files, everything git doesn't ignore included, in git's
normalised form. Applying it SHALL convert line endings and filters as git does for the theatre's working tree.

#### Scenario: A CRLF file
- **WHEN** a file checked out with CRLF line endings is changed in a worktree, captured and applied to the theatre
- **THEN** the theatre's file has CRLF line endings and the worktree's content

#### Scenario: An untracked file
- **WHEN** an actor writes a new file that git doesn't ignore in a worktree
- **THEN** the captured diff adds it

#### Scenario: An ignored file
- **WHEN** an actor writes a file in a worktree that git ignores
- **THEN** the captured diff leaves it out

### Requirement: The git adapter applies a diff only when all of it applies
The git adapter SHALL check a diff against the theatre's working tree before applying it, and SHALL apply it only when
every file applies cleanly. When the check fails, it SHALL name the files that don't apply, and leave every file as it
was.

#### Scenario: One file of two conflicts
- **WHEN** a diff changes `a.txt` and `b.txt`, and `b.txt` has changed in the theatre on the same lines
- **THEN** applying is refused, naming `b.txt`, and `a.txt` is unchanged too
