# Spec Delta

## ADDED Requirements

### Requirement: The git adapter re-reads the branch and HEAD with one command once HEAD has a commit
When the git adapter has to read the branch and HEAD again, it SHALL run one git command when HEAD points at a commit,
whether on a branch or detached. The answers SHALL be exactly what `git symbolic-ref --quiet --short HEAD` and
`git rev-parse --verify --quiet HEAD` report, so the branch keeps git's short name, disambiguation included. An unborn
HEAD MAY take more commands, but no more than three.

#### Scenario: A re-read on a branch runs one command
- **WHEN** the branch and HEAD are read again after a commit on a branch
- **THEN** one git command runs, and the branch and HEAD it reports are git's

#### Scenario: A re-read on a detached HEAD runs one command
- **WHEN** the branch and HEAD are read again after HEAD is detached at a commit
- **THEN** one git command runs, and there is no branch and HEAD is that commit

#### Scenario: An ambiguous branch name keeps git's disambiguation
- **WHEN** the checked-out branch shares its name with a tag or another ref, or its name begins with `heads/` or
  `tags/`
- **THEN** the branch reported is exactly what `git symbolic-ref --quiet --short HEAD` prints, such as `heads/main`

#### Scenario: A file named HEAD in the work tree changes nothing
- **WHEN** the work tree holds a file or directory named `HEAD`
- **THEN** the branch and HEAD are read the same way and report git's answers

#### Scenario: An unborn HEAD reports its branch and no commit
- **WHEN** the branch and HEAD are read in a repository with no commit yet, on its initial branch or an orphan branch
- **THEN** the branch is the unborn branch's short name and there is no HEAD, read in no more than three git commands

#### Scenario: A failure is still reported as a git failure
- **WHEN** reading the branch and HEAD fails for a reason other than an unborn HEAD, such as a repository git refuses
  to read
- **THEN** the failure names the git command and what git said, as any failed git call does
