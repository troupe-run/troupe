## ADDED Requirements

### Requirement: Every release's notes match its changelog section
After each release run on `main`, the release workflow SHALL compare the GitHub release notes of every tag the
manifest's versions name with that version's section of the component's changelog. The heading's date MAY differ.
Any other difference SHALL fail the run, naming each release that differs. It SHALL check even when release-please
failed.

#### Scenario: Notes published from an inline body
- **WHEN** every release the manifest names has notes equal to its changelog section, apart from the heading's date
- **THEN** the check passes

#### Scenario: Notes that lost their non-ASCII text
- **WHEN** a release's notes read `### � BREAKING CHANGES` where its changelog section reads
  `### ⚠ BREAKING CHANGES`
- **THEN** the run fails, naming that release, the first line that differs, and the number of U+FFFD characters in
  its notes

#### Scenario: Notes that swallowed other components' blocks
- **WHEN** a release's notes hold its changelog section followed by text from other components
- **THEN** the run fails, naming that release

#### Scenario: A tag with no release
- **WHEN** the manifest names a tag that has no GitHub release
- **THEN** the run fails, naming the tag as having no notes to compare

#### Scenario: A version with no changelog section
- **WHEN** a component's changelog has no section for the version the manifest records
- **THEN** the check fails, naming the changelog and the version, rather than passing it

#### Scenario: A member that hasn't released
- **WHEN** a workspace member's version in the manifest is `0.0.0`
- **THEN** the check doesn't look for its release

### Requirement: A release's notes can be repaired from its changelog
The release guide SHALL describe how to repair a release whose notes differ from its changelog section. The check
SHALL be able to print the changelog section for a given tag, to publish as that release's notes. Editing a published
release is the owner's to do.

#### Scenario: Printing the notes to publish
- **WHEN** the check is asked for the section of `troupe-plugin-sdk-v0.1.0`
- **THEN** it prints that version's section of `packages/troupe-plugin-sdk/CHANGELOG.md`

#### Scenario: Asking for a tag the config doesn't name
- **WHEN** the check is asked for the section of a tag whose component isn't in the config
- **THEN** it fails, naming the tag, rather than printing anything
