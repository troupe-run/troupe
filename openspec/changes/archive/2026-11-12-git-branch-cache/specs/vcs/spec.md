## MODIFIED Requirements

### Requirement: The branch token changes whenever the branch or HEAD moves
Each VCS adapter SHALL give a branch token: a value that is cheap to compare. It SHALL change whenever the checked-out
branch, its short name, HEAD, or what is committed changes. That covers a change made by this process or any other, and
in the git adapter it SHALL hold with either ref storage (files or reftable), with reflogs on or off, and in a linked
worktree. Reading the token SHALL run no command while nothing has moved.

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

#### Scenario: A ref sharing the branch's name changes its short name
- **WHEN** a ref that git weighs when shortening the checked-out branch's name, such as a tag with the branch's name,
  is created or deleted, with either ref storage, in the main worktree or a linked one
- **THEN** the token differs from the one read before, and the branch reported is git's new short name, such as
  `heads/main` once a tag `main` exists and `main` again once it's deleted

#### Scenario: A symbolic ref shares the branch's name
- **WHEN** a ref sharing the checked-out branch's name is a symbolic ref, so the short name depends on whether its
  target exists, and its target is then created or deleted
- **THEN** the branch reported follows git's short name; with the files ref storage, the branch is read through git
  again on every call while that ref exists, and with reftable, whose tables hold the ref and its target, it's read
  again only when they change

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
- **WHEN** any sequence of commits, switches, detaches, merges, resets, branch renames, ref packing, moves from
  another worktree, and creating or deleting a tag or other ref named after the checked-out branch runs, with either
  ref storage and reflogs on or off
- **THEN** after each operation the adapter reports the same branch and HEAD as an adapter that caches nothing
