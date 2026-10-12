# Spec Delta

## Purpose

The version-control port troupe reads the working tree's state through, so the event store and lineage work the
same whether a theatre uses git or no version control at all.

## ADDED Requirements

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
