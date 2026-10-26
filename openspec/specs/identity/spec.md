# identity Specification

## Purpose

Capability: `cap:identity`

Works out who is acting, through an ordered, pluggable chain of identity sources, so that every event names a real
actor and troupe fails rather than guesses when nobody can be identified.

## Requirements

### Requirement: Identity comes from an ordered chain of sources
The acting identity SHALL be resolved by asking each identity source in the chain, in order, and taking the first
that answers. The chain SHALL be a named setting whose default is defined in one place. Sources SHALL be pluggable,
so they can be added, removed and reordered without changing the code that asks.

#### Scenario: The first source that answers wins
- **WHEN** the first source in the chain has no answer and the second has one
- **THEN** the identity is the second source's answer

#### Scenario: Reordering the chain
- **WHEN** the chain is configured with the OS login before the VCS identity, and both answer
- **THEN** the identity is the OS login's answer

### Requirement: The default chain
The default chain SHALL be: the `TROUPE_ACTOR` override, then the identity the version-control system is configured
with (git's `user.email` for the theatre), then the OS login. The VCS source SHALL answer only when the VCS adapter
provides an identity.

#### Scenario: The override wins
- **WHEN** `TROUPE_ACTOR` is `human:ada@example.com` and git's `user.email` is set
- **THEN** the identity is the human `ada@example.com`, resolved by the override

#### Scenario: Git user email
- **WHEN** `TROUPE_ACTOR` is unset and the theatre's git `user.email` is `ada@example.com`
- **THEN** the identity is the human `ada@example.com`, resolved by the VCS source

#### Scenario: Git user email from the user's global configuration
- **WHEN** `TROUPE_ACTOR` is unset and `user.email` is set only in the user's global git configuration
- **THEN** the identity is that email, resolved by the VCS source, not by the OS login

#### Scenario: The OS login
- **WHEN** `TROUPE_ACTOR` is unset and git has no `user.email`, or the theatre uses the plain filesystem adapter
- **THEN** the identity is the OS login name, resolved by the OS login source

### Requirement: The override has one form
`TROUPE_ACTOR` SHALL be `human:<id>` or `agent:<id>`, with a non-empty ID. Any other non-empty value SHALL fail
with an error naming the value and the accepted forms, without falling through to the next source. An empty value
SHALL count as unset.

#### Scenario: A malformed override
- **WHEN** `TROUPE_ACTOR` is `ada`
- **THEN** the command fails with an error that names the value and shows `human:<id>` and `agent:<id>`

#### Scenario: An empty override is unset
- **WHEN** `TROUPE_ACTOR` is set to the empty string
- **THEN** it counts as unset, and the next source in the chain is asked

### Requirement: A malformed or ambiguous answer is an error
A source that finds no identity SHALL pass to the next source. A source that finds something it can't use cleanly
(a malformed value, or more than one candidate) SHALL fail the command with an error naming the source, the value
and the fix. It SHALL NOT fall through to the next source or to a default.

#### Scenario: Two git emails
- **WHEN** `TROUPE_ACTOR` is unset and the theatre's git configuration holds two `user.email` values
- **THEN** the command fails with an ambiguity error naming the VCS source and both values
- **AND** the OS login is not used

#### Scenario: An unknown source in the chain
- **WHEN** the chain names a source that isn't installed
- **THEN** the command fails with an error naming the unknown source and the installed ones

#### Scenario: Absence still falls through
- **WHEN** the VCS source finds no `user.email` at all
- **THEN** the next source in the chain is asked

### Requirement: No identity, no command
When no source in the chain answers, a command that would record an event SHALL fail with an error that lists the
sources tried and how to provide an identity. It SHALL NOT record `unknown`, an empty ID, or a guess.

#### Scenario: Nothing resolves
- **WHEN** every source in the chain has no answer and a command would record an event
- **THEN** it fails with an error naming each source tried and the fix
- **AND** nothing is written

### Requirement: Lineage records which source answered
The resolved identity SHALL carry the name of the source that resolved it, and lineage SHALL record it.

#### Scenario: Source recorded
- **WHEN** an event is recorded with an identity from git's `user.email`
- **THEN** its lineage actor names the VCS source
