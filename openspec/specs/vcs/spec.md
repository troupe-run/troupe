# vcs Specification

## Purpose

Capability: `cap:vcs`

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

### Requirement: The VCS port reports a path's merge sides
The VCS port SHALL report, for theatre-relative paths, each one git left unmerged or merged cleanly in the merge in
progress or in HEAD's merge commit: each side's bytes (none for a side without the file), the bytes the merge gave,
and whether it was conflicted or clean. A path in no merge SHALL be left out. An adapter with no merges SHALL report
none.

#### Scenario: The plain filesystem adapter
- **WHEN** merge sides are asked for from the plain filesystem adapter
- **THEN** it reports none

### Requirement: The git adapter reads a conflicted path's sides from the index
For a path git's index holds unmerged, the git adapter SHALL report it as conflicted, with ours and theirs read from
the index's stages, byte for byte. A side the index has no stage for SHALL be reported as absent.

#### Scenario: Both branches changed the file
- **WHEN** a merge leaves `.troupe/actors/tester.yaml` with conflict markers
- **THEN** the adapter reports it conflicted, with each branch's version of the file as its sides

#### Scenario: Removed on one branch
- **WHEN** a merge stops because one branch removed `.troupe/actors/tester.md` and the other changed it
- **THEN** the adapter reports it conflicted, with ours absent and theirs the changed file

#### Scenario: A rebase stops on the file
- **WHEN** a rebase or cherry-pick stops with `.troupe/actors/tester.yaml` unmerged
- **THEN** the adapter reports it conflicted, with its sides from the index

### Requirement: The git adapter reports a clean merge only when it reproduces it
For a path that isn't unmerged, the git adapter SHALL report it as merged cleanly only during a merge in progress, or
when HEAD is a merge of two parents, and only when git, merging the two parents again, reproduces for that path, with
no conflict, exactly the bytes the merge gave. Otherwise it SHALL leave the path out.

#### Scenario: A clean merge in progress
- **WHEN** a merge stops on another file's conflict, and git merged `.troupe/actors/tester.md` cleanly
- **THEN** the adapter reports it merged cleanly, with HEAD's and the merged branch's versions as its sides, and
  the index's version as what the merge gave

#### Scenario: A committed clean merge
- **WHEN** HEAD is a merge commit in which git merged `.troupe/actors/tester.md` cleanly
- **THEN** the adapter reports it merged cleanly, with each parent's version as its sides

#### Scenario: A merge someone edited before committing it
- **WHEN** HEAD is a merge commit whose `.troupe/actors/tester.md` differs from the clean merge of its parents'
  versions
- **THEN** the adapter leaves the path out

#### Scenario: A merge of more than two parents
- **WHEN** HEAD is an octopus merge
- **THEN** the adapter reports no clean merges

#### Scenario: No merge
- **WHEN** no merge is in progress and HEAD has one parent
- **THEN** the adapter reports no clean merges

### Requirement: The VCS port marks paths resolved
The VCS port SHALL mark theatre-relative paths resolved, given for each one the conflicted merge sides the caller read
and the bytes to stage, or none to stage its removal. It SHALL report, for each path, whether it was marked, and if
not, why. An adapter with no index SHALL mark none and say so.

#### Scenario: The plain filesystem adapter
- **WHEN** the plain filesystem adapter is asked to mark `.troupe/actors/tester.yaml` resolved
- **THEN** it marks nothing, and reports that it has no index

### Requirement: The git adapter stages exactly the given bytes
For a path still unmerged with the stages the caller read, the git adapter SHALL replace every unmerged entry with
one stage-0 entry holding the given bytes, stored as `git add` would store them, or SHALL remove every entry for the
path when no bytes are given. It SHALL NOT read the working file, and SHALL change no other path's entry.

#### Scenario: A conflicted file
- **WHEN** `.troupe/actors/tester.yaml` has stages 1, 2 and 3, and the adapter is asked to mark it resolved with
  bytes `B`
- **THEN** `git ls-files -s` lists one stage-0 entry for it whose blob is `B`, and `git ls-files -u` lists nothing
  for it
- **AND** a merge in progress can be committed without another `git add`

#### Scenario: A removal
- **WHEN** `.troupe/actors/tester.md` has stages 1 and 3, and the adapter is asked to mark it resolved with no bytes
- **THEN** the index has no entry for it

#### Scenario: The file changed on disk
- **WHEN** the working file holds bytes `C`, and the adapter is asked to mark it resolved with bytes `B`
- **THEN** the index holds `B`

### Requirement: The git adapter leaves a path whose stages have changed
The git adapter SHALL mark a path resolved only when the index still holds exactly the unmerged stages, modes and
objects, the caller read. Otherwise it SHALL leave the path's entries unchanged and report that the index changed.

#### Scenario: Already resolved by the person
- **WHEN** the adapter read `.troupe/actors/tester.yaml` as conflicted, and the person then ran `git add` on it
- **THEN** asking the adapter to mark it resolved leaves its entry as `git add` left it, and reports that the index
  changed

#### Scenario: Not unmerged any more
- **WHEN** the merge was aborted after the adapter read the path's sides
- **THEN** the adapter marks nothing, and reports that the index changed

### Requirement: The VCS port says whether a directory is in a repository
A VCS adapter SHALL say whether its directory is in one of its repositories. When it isn't, the adapter SHALL say so
with `vcs.not-a-repository`, naming the directory and how to make a repository with that version control. The plain
filesystem adapter SHALL count every directory as in one.

#### Scenario: The plain filesystem adapter
- **WHEN** the plain filesystem adapter is asked about any directory
- **THEN** it says the directory is in a repository

### Requirement: The git adapter's repository is a work tree
The git adapter SHALL count a directory as in a repository only when git reports it inside a work tree, so a
directory outside any repository, a repository's git directory, and a bare repository are not. Its fix SHALL name
`git init`.

#### Scenario: Outside any repository
- **WHEN** the git adapter is asked about a directory that no git repository holds
- **THEN** it reports `vcs.not-a-repository`, naming the directory, with a fix that names `git init`

#### Scenario: A subdirectory of a work tree
- **WHEN** the git adapter is asked about `app/` of a git work tree with no commits
- **THEN** it says the directory is in a repository

#### Scenario: A bare repository
- **WHEN** the git adapter is asked about a bare repository's directory
- **THEN** it reports `vcs.not-a-repository`

### Requirement: The git adapter reads the branch and HEAD in one command once HEAD has a commit
When the git adapter has to read the branch and HEAD again, it SHALL run one git command when HEAD points at a commit,
whether on a branch or detached. The branch SHALL be git's short name as `git rev-parse --abbrev-ref=loose HEAD`
reports it, disambiguation included, and an unborn branch SHALL report the short name it will have once it has a
commit. An unborn HEAD MAY take more commands, no more than its scenarios below allow.

#### Scenario: A re-read on a branch runs one command
- **WHEN** the branch and HEAD are read again after a commit on a branch
- **THEN** one git command runs, and the branch and HEAD it reports are git's

#### Scenario: A re-read on a detached HEAD runs one command
- **WHEN** the branch and HEAD are read again after HEAD is detached at a commit
- **THEN** one git command runs, and there is no branch and HEAD is that commit

#### Scenario: An ambiguous branch name keeps git's disambiguation
- **WHEN** the checked-out branch shares its name with a tag or another ref, or its name begins with `heads/` or
  `tags/`
- **THEN** the branch reported is exactly what `git rev-parse --abbrev-ref=loose HEAD` prints, such as `heads/main`

#### Scenario: A file named HEAD in the work tree changes nothing
- **WHEN** the work tree holds a file or directory named `HEAD`
- **THEN** the branch and HEAD are read the same way and report git's answers

#### Scenario: An unborn HEAD reports its branch and no commit
- **WHEN** the branch and HEAD are read in a repository with no commit yet, on its initial branch or an orphan branch
- **THEN** the branch is the unborn branch's short name and there is no HEAD

#### Scenario: A symbolic ref sharing an unborn branch's name doesn't change it
- **WHEN** a symbolic ref named after the unborn checked-out branch exists, such as a tag `feature` pointing at a
  missing `refs/heads/gone` while HEAD is on an unborn `feature`, with either ref storage
- **THEN** the branch reported is `feature`, the name reported once `feature` has a commit, not the name of the
  symbolic ref's target

#### Scenario: An unborn HEAD the files show is read in three commands
- **WHEN** the branch and HEAD are read again while HEAD names a loose ref that doesn't exist, in a repository that
  keeps its refs as files and has no `packed-refs`, and no file at the top of the git directory has the branch's name
- **THEN** no more than three git commands run

#### Scenario: Root refs named after an unborn branch cost one command more
- **WHEN** the branch and HEAD are read again while HEAD is unborn in a repository that keeps its refs as files, and a
  file at the top of the git directory has the branch's name or `heads/` and the branch's name
- **THEN** git is asked about all of them in one more command

#### Scenario: Any other unborn HEAD is read in five commands
- **WHEN** the branch and HEAD are read again while HEAD is unborn in a repository with `packed-refs` or reftable
- **THEN** no more than five git commands run, whatever refs share the branch's name

#### Scenario: An unborn branch's name that git's answers can't settle is refused
- **WHEN** HEAD is on an unborn branch `x`, `x` is ambiguous, and whether `heads/x` is a ref at the top of the git
  directory can't be told because two refs under `refs/` are also named `heads/x`
- **THEN** reading the branch is refused with `vcs.short-name-undecided`, naming the branch, the name and the refs,
  and the fix says a commit on the branch lets git name it

#### Scenario: A failure is still reported as a git failure
- **WHEN** reading the branch and HEAD fails for a reason other than an unborn HEAD, such as a repository git refuses
  to read
- **THEN** the failure names the git command and what git said, as any failed git call does
