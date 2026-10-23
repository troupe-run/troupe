# Spec Delta

## ADDED Requirements

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
