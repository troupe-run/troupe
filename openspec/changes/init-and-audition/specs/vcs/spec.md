# Spec Delta

## ADDED Requirements

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
