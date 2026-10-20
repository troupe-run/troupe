## ADDED Requirements

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
