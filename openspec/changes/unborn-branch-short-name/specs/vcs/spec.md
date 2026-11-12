## ADDED Requirements

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

## REMOVED Requirements

### Requirement: The git adapter re-reads the branch and HEAD with one command once HEAD has a commit
**Reason**: Its scenario "Any other unborn HEAD is read in four commands" is no longer true: an unborn HEAD under
reftable takes five, since git is asked whether a root ref shares the branch's name (unborn-branch-short-name design
D2). OpenSpec can't drop or rename a scenario in a MODIFIED requirement.
**Migration**: Replaced by "The git adapter reads the branch and HEAD in one command once HEAD has a commit", with the
same text, git's short name as `rev-parse --abbrev-ref=loose` gives it, and the new command limits for an unborn HEAD.
