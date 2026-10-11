# Spec Delta

## MODIFIED Requirements

### Requirement: Pull requests close an issue
In a Claude Code session, opening a pull request into this repository SHALL be refused unless its description closes
an issue with a closing keyword (`Closes`, `Fixes` or `Resolves`, followed by an issue reference). A pull request
into a different repository is not checked. When the pull request's target repository can't be determined, it SHALL
be treated as this repository.

#### Scenario: A PR without a closing reference
- **WHEN** an agent opens a pull request into this repository whose description closes no issue
- **THEN** the request is refused and the message says to add `Closes #<issue>`

#### Scenario: A PR that closes an issue
- **WHEN** an agent opens a pull request whose description contains `Closes #22`
- **THEN** the request goes ahead

#### Scenario: A PR into another repository
- **WHEN** an agent opens a pull request into another repository, such as `troupe-run/.github`, whose description
  closes no issue
- **THEN** the request goes ahead

#### Scenario: A PR that names this repository explicitly
- **WHEN** an agent opens a pull request that names this repository as its target, in any form `gh` accepts, and
  its description closes no issue
- **THEN** the request is refused, as for any PR into this repository

#### Scenario: A PR whose target can't be determined
- **WHEN** an agent opens a pull request whose description closes no issue, and its target repository can't be
  worked out (an unrecognisable repository name, or this clone has no remote to compare with)
- **THEN** the request is refused, as for a PR into this repository
